# ECPKart64

A Lattice ECP5 based FPGA Flash Cart for the Nintendo 64



# Colorlight i5

Build and load the bitstream:

```
make load_bitstream
```


Build and load the firmware (which handles ROM upload as well as CIC):

```
make load_app
```


Reboot litex to run the firmware:

``` 
litex> reboot
```


Exit litex and upload a z64 ROM (and set a slower bus speed with header 0x80374040):

```
python3 gateware/ecpkart64/uploader2.py --port /dev/ttyACM0 --baudrate 115200 --header 0x80374040 --file rom.z64
```


Connect to litex and start CIC:

```
lxterm /dev/ttyACM0
litex> cic
```


Power the console on :-)




To run the logic analyzer:

Start the litex server:

```
make litex_server
```


Start the analylzer client and set a trigger condition:

```
litescope_cli -v main_n64_n64_addr 0x10000040
```

Display dump:

```
gtkwave dump.vcd
```



Known Limitations:

- Firmware is stored in SDRAM, which takes 16KB out of the available 8MB (which happens to be the smallest ROM size... hopefully the last 16KB can be shaved off from most ROMs?)
- UART baudrate is slow, which is especially annoying to upload ROMs



Pins wiring:

P2 Header:

    Pin 3: A15 (Cartridge Pad 3)
    Pin 4: A14 (Cartridge Pad 4)
    Pin 5: A13 (Cartridge Pad 5)
    Pin 6: A12 (Cartridge Pad 7)
    Pin 7: WR (Cartridge Pad 8)
    Pin 9: RD (Cartridge Pad 10)
    Pin 12: A11 (Cartridge Pad 11)
    Pin 13: A10 (Cartridge Pad 12)

    Pin 28: A0 (Cartridge Pad 28)
    Pin 27: A1 (Cartridge Pad 29)
    Pin 26: A2 (Cartridge Pad 30)
    Pin 25: A3 (Cartridge Pad 32)
    Pin 24: ALEL (Cartridge Pad 33)
    Pin 22: ALEH (Cartridge Pad 35)
    Pin 19: A4 (Cartridge Pad 36)
    Pin 18: A5 (Cartridge Pad 37)

P3 Header:

    Pin 3: A9 (Cartridge Pad 15)
    Pin 4: A8 (Cartridge Pad 16)
    Pin 5: CIC DIO (Cartridge Pad 18)
    Pin 6: 1_6_CLK (Cartridge Pad 19)
    Pin 7: RST (Cartridge Pad 20)
    Pin 9: SDAT (Cartridge Pad 21)

    Pin 28: A6 (Cartridge Pad 40)
    Pin 27: A7 (Cartridge Pad 41)
    Pin 26: CIC_DCLK (Cartridge Pad 43)
    Pin 25: NMI (Cartridge Pad 45)

P5 Header:

    Pin 3: UARTBone RX
    Pin 28: UARTBone TX



![](colorlight_i5_ext_board_pin_mapping.svg)

