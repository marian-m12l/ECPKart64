#!/usr/bin/env python3

#
# This file is part of LiteX-Boards.
#
# Copyright (c) 2021 Kazumoto Kojima <kkojima@rr.iij4u.or.jp>
# SPDX-License-Identifier: BSD-2-Clause

import os
import argparse
import sys

from migen import *

from litex.build.io import DDROutput

from litex.build.lattice.trellis import trellis_args, trellis_argdict

from litex.soc.cores.clock import *
from litex.soc.integration.soc_core import *
from litex.soc.integration.builder import *
from litex.soc.cores.video import VideoECP5HDMIPHY
from litex.soc.cores.led import LedChaser

from litex.soc.interconnect.csr import *

from litedram.modules import M12L64322A # Compatible with EM638325-6H.
from litedram.phy import GENSDRPHY, HalfRateGENSDRPHY

from liteeth.phy.ecp5rgmii import LiteEthPHYRGMII



from litex.soc.integration.soc import SoCRegion
from litex.soc.interconnect import wishbone
from litex.soc.cores.gpio import GPIOTristate, GPIOIn
from litescope import LiteScopeAnalyzer

from ..platforms import colorlight_i5

from ..cart import N64Cart, N64CartBus

# CRG ----------------------------------------------------------------------------------------------

class _CRG(Module):
    def __init__(self, platform, sys_clk_freq, use_internal_osc=False, with_usb_pll=False, with_video_pll=False, sdram_rate="1:1"):
        self.rst = Signal()
        self.clock_domains.cd_sys    = ClockDomain()
        if sdram_rate == "1:2":
            self.clock_domains.cd_sys2x    = ClockDomain()
            self.clock_domains.cd_sys2x_ps = ClockDomain(reset_less=True)
        else:
            self.clock_domains.cd_sys_ps = ClockDomain(reset_less=True)
        self.clock_domains.cd_analyzer = ClockDomain()

        # # #

        # Clk / Rst
        if not use_internal_osc:
            clk = platform.request("clk25")
            clk_freq = 25e6
        else:
            clk = Signal()
            div = 5
            self.specials += Instance("OSCG",
                                p_DIV = div,
                                o_OSC = clk)
            clk_freq = 310e6/div

        #rst_n = platform.request("cpu_reset_n")

        # PLL
        self.submodules.pll = pll = ECP5PLL()
        self.comb += pll.reset.eq(self.rst)
        pll.register_clkin(clk, clk_freq)
        pll.create_clkout(self.cd_sys,    sys_clk_freq)
        if sdram_rate == "1:2":
            pll.create_clkout(self.cd_sys2x,    2*sys_clk_freq)
            pll.create_clkout(self.cd_sys2x_ps, 2*sys_clk_freq, phase=180) # Idealy 90° but needs to be increased.
        else:
           pll.create_clkout(self.cd_sys_ps, sys_clk_freq, phase=180) # Idealy 90° but needs to be increased.
        

        # Clock domain for litescopre analyzer
        # Use system clock for high speed protocol (ROM accesses)
        pll.create_clkout(self.cd_analyzer,    sys_clk_freq)
        # Use slower clock for low speed protocol (CIC)
        #pll.create_clkout(self.cd_analyzer,    sys_clk_freq/14) # Slower clock for analyzer ???
        # Generate a "manual" clock signal from sysclock + counter
        counter_preload = 200   # Divider == 200 -> 300KHz
        counter = Signal(max=counter_preload + 1)
        tick = Signal()
        slowclk = Signal()
        self.comb += tick.eq(counter == 0)
        self.sync += If(tick, slowclk.eq(~slowclk), counter.eq(counter_preload)).Else(counter.eq(counter - 1))
        #self.comb += self.cd_analyzer.clk.eq(slowclk)

        # SDRAM clock
        sdram_clk = ClockSignal("sys2x_ps" if sdram_rate == "1:2" else "sys_ps")
        self.specials += DDROutput(1, 0, platform.request("sdram_clock"), sdram_clk)

# BaseSoC ------------------------------------------------------------------------------------------

class BaseSoC(SoCCore):
    mem_map = {**SoCCore.mem_map, **{"spiflash": 0xd0000000}}
    def __init__(self, board="i5", revision="7.0", sys_clk_freq=60e6, with_ethernet=False,
                 with_etherbone=False, local_ip="", remote_ip="", eth_phy=0, with_led_chaser=True, 
                 use_internal_osc=False, sdram_rate="1:1", with_video_terminal=False,
                 with_video_framebuffer=False, **kwargs):
        board = board.lower()
        assert board in ["i5"]
        if board == "i5":
            platform = colorlight_i5.Platform(revision=revision)

        # SoCCore ----------------------------------------------------------------------------------
        SoCCore.__init__(self, platform, int(sys_clk_freq),
            ident          = "LiteX SoC on Colorlight " + board.upper(),
            ident_version  = True,
            uart_baudrate  = 460800,
            **kwargs)

        # CRG --------------------------------------------------------------------------------------
        with_usb_pll = kwargs.get("uart_name", None) == "usb_acm"
        with_video_pll = with_video_terminal or with_video_framebuffer
        self.submodules.crg = _CRG(platform, sys_clk_freq, use_internal_osc=use_internal_osc, with_usb_pll=with_usb_pll, with_video_pll=with_video_pll, sdram_rate=sdram_rate)

        # Firmware RAM (To ease initial LiteDRAM calibration support) ------------------------------
        #self.add_ram("firmware_ram", 0x20000000, 0x4000)   # FIXME Is there enough block ram for the firmware?

        # SDR SDRAM --------------------------------------------------------------------------------
        if not self.integrated_main_ram_size:
            sdrphy_cls = HalfRateGENSDRPHY if sdram_rate == "1:2" else GENSDRPHY
            self.submodules.sdrphy = sdrphy_cls(platform.request("sdram"))
            self.add_sdram("sdram",
                phy           = self.sdrphy,
                module        = M12L64322A(sys_clk_freq, sdram_rate),
                l2_cache_size = kwargs.get("l2_size", 1024) #FIXME 8192 or 0?
            )

        # Add an extra dedicated wishbone bus for the n64 cart
        sdram_port = self.sdram.crossbar.get_port(data_width=16)


        # N64 Peripheral Interface -----------------------------------------------------------------

        n64_pads = platform.request("n64")

        self.submodules.n64 = n64cart = N64Cart(
                pads         = n64_pads,
                sdram_port   = sdram_port,
                sdram_wait   = self.sdram.controller.refresher.timer.wait,
                fast_cd      = "sys",
                #fast_cd      = "sys4x",
        )
        #self.bus.add_slave("n64slave", self.n64.wb_slave, region=SoCRegion(origin=0x30000000, size=0x10000))

        n64cic = self.platform.request("n64cic")
        self.submodules.n64cic_si_clk   = GPIOIn(n64cic.si_clk)
        self.submodules.n64cic_cic_dclk = GPIOIn(n64cic.cic_dclk)
        self.submodules.n64cic_cic_dio  = GPIOTristate(n64cic.cic_dio)
        self.submodules.n64cic_eep_sdat = GPIOTristate(n64cic.eep_sdat)
        self.submodules.n64_cold_reset  = GPIOIn(n64_pads.cold_reset)


        # Create signals mirroring CIC DIO state for litescope analyzer
        cicdiosignal_in = Signal()
        cicdiosignal_out = Signal()
        cicdiosignal_oe = Signal()
        self.comb += cicdiosignal_in.eq(self.n64cic_cic_dio._in.status)
        self.comb += cicdiosignal_out.eq(self.n64cic_cic_dio._out.storage)
        self.comb += cicdiosignal_oe.eq(self.n64cic_cic_dio._oe.storage)

        analyzer_signals = [
            #n64cic.cic_dio,
            cicdiosignal_in,
            cicdiosignal_out,
            cicdiosignal_oe,
            n64cic.cic_dclk,
            n64cart.n64cartbus.aleh,
            n64cart.n64cartbus.alel,
            n64cart.n64cartbus.read,
            n64cart.n64cartbus.write,
            n64cart.n64cartbus.nmi,

            n64cart.n64cartbus.ad_oe,
            n64cart.n64cartbus.ad_out,
            n64cart.n64cartbus.ad_in,

            n64cart.n64cartbus.n64_addr,
            n64cart.n64cartbus.read_active,

            n64cart.n64cartbus.fsm.state,

            n64cart.n64cartbus.n64_addr_l,
            n64cart.n64cartbus.n64_addr_h,
            n64cart.n64cartbus.sdram_data,
            n64cart.n64cartbus.n64_ad_out_r,

            n64cart.n64cartbus.sdram_sel,
            n64cart.n64cartbus.custom_sel,

            sdram_port.flush,
            sdram_port.cmd.addr,
            sdram_port.cmd.we,
            sdram_port.cmd.valid,
            sdram_port.cmd.ready,
            sdram_port.rdata.ready,
            sdram_port.rdata.valid,
            sdram_port.rdata.data,
            sdram_port.flush,

            #self.sdram.controller.refresher.fsm,
            #self.sdram.controller.refresher.timer.count,
            #self.sdram.controller.refresher.timer.wait,
        ]
        self.submodules.analyzer = LiteScopeAnalyzer(analyzer_signals,
            depth        = 1024,
            clock_domain = "analyzer",
            csr_csv      = "analyzer.csv")

        self.add_uartbone(name="serial", baudrate=115200)   # FIXME Higher baudrate?


# Build --------------------------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="LiteX SoC on Colorlight i5")
    parser.add_argument("--build",            action="store_true",      help="Build bitstream")
    parser.add_argument("--load",             action="store_true",      help="Load bitstream")
    parser.add_argument("--board",            default="i5",         help="Board type: i5 (default)")
    parser.add_argument("--revision",         default="7.0", type=str,  help="Board revision: 7.0 (default)")
    parser.add_argument("--sys-clk-freq",     default=60e6,             help="System clock frequency (default: 60MHz)")
    ethopts = parser.add_mutually_exclusive_group()
    ethopts.add_argument("--with-ethernet",   action="store_true",      help="Enable Ethernet support")
    ethopts.add_argument("--with-etherbone",  action="store_true",      help="Enable Etherbone support")
    parser.add_argument("--remote-ip",        default="192.168.1.100",  help="Remote IP address of TFTP server")
    parser.add_argument("--local-ip",         default="192.168.1.50",   help="Local IP address")
    sdopts = parser.add_mutually_exclusive_group()
    sdopts.add_argument("--with-spi-sdcard",  action="store_true",	help="Enable SPI-mode SDCard support")
    sdopts.add_argument("--with-sdcard",      action="store_true",	help="Enable SDCard support")
    parser.add_argument("--eth-phy",          default=0, type=int,      help="Ethernet PHY: 0 (default) or 1")
    parser.add_argument("--use-internal-osc", action="store_true",      help="Use internal oscillator")
    parser.add_argument("--sdram-rate",       default="1:1",            help="SDRAM Rate: 1:1 Full Rate (default), 1:2 Half Rate")
    viopts = parser.add_mutually_exclusive_group()
    viopts.add_argument("--with-video-terminal",    action="store_true", help="Enable Video Terminal (HDMI)")
    viopts.add_argument("--with-video-framebuffer", action="store_true", help="Enable Video Framebuffer (HDMI)")
    builder_args(parser)
    soc_core_args(parser)
    trellis_args(parser)
    args = parser.parse_args()

    soc = BaseSoC(board=args.board, revision=args.revision,
        sys_clk_freq           = int(float(args.sys_clk_freq)),
        with_ethernet          = args.with_ethernet,
        with_etherbone         = args.with_etherbone,
        local_ip               = args.local_ip,
        remote_ip              = args.remote_ip,
        eth_phy                = args.eth_phy,
        use_internal_osc       = args.use_internal_osc,
        sdram_rate             = args.sdram_rate,
        l2_size	               = args.l2_size,
        with_video_terminal    = args.with_video_terminal,
        with_video_framebuffer = args.with_video_framebuffer,
        **soc_core_argdict(args)
    )
    soc.platform.add_extension(colorlight_i5._sdcard_pmod_io)
    if args.with_spi_sdcard:
        soc.add_spi_sdcard()
    if args.with_sdcard:
        soc.add_sdcard()

    builder = Builder(soc, **builder_argdict(args))

    builder.build(**trellis_argdict(args), run=args.build)

    if args.load:
        prog = soc.platform.create_programmer()
        prog.load_bitstream(os.path.join(builder.gateware_dir, soc.build_name + ".bit"))

if __name__ == "__main__":
    main()