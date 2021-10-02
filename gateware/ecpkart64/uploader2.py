#!/usr/bin/env python3

#
# This file is part of ECPKart64.
#
# Copyright (c) 2021 Konrad Beckmann <konrad.beckmann@gmail.com
# SPDX-License-Identifier: BSD-2-Clause

import os
import argparse

from struct import unpack
from litex import RemoteClient
import serial


SDRAM_SIZE = 8*1024*1024
FIRMWARE_RESERVED_MEMORY = 16*1024
CHUNK_SIZE = 16*1024


def parse_args():
    parser = argparse.ArgumentParser(description="""ECPKart64 Dump Utility""")
    parser.add_argument("--csr-csv", default="csr.csv", help="SoC CSV file")
    parser.add_argument("--file", default="bootrom.z64", help="z64 ROM file")
    parser.add_argument("--port", default="/dev/ttyUSB1", help="port")
    parser.add_argument("--baudrate", default="460800", help="baud")
    parser.add_argument("--header", type=lambda x: int(x, 0), default=0x80371240, help="Override the first word of the ROM")
    parser.add_argument("--cic", action="store_true", help="Starts the CIC app after upload")
    args = parser.parse_args()
    return args

def main():
    args = parse_args()

    # Create and open remote control.
    if not os.path.exists(args.csr_csv):
        raise ValueError("{} not found. This is necessary to load the 'regs' of the remote. Try setting --csr-csv here to "
                         "the path to the --csr-csv argument of the SoC build.".format(args.csr_csv))

    if not os.path.exists(args.file):
        raise ValueError("{} not found.".format(args.csr_csv))

    bus = RemoteClient(csr_csv=args.csr_csv, debug=True)
    base = bus.mems.main_ram.base

    port = serial.serial_for_url(args.port, args.baudrate)

    try:
        with open(args.file, "rb") as f:
            data_bytes = f.read()
            totalSize = len(data_bytes)

            # Make sure ROM fits in available SDRAM memory
            if totalSize > (SDRAM_SIZE - FIRMWARE_RESERVED_MEMORY):
                raise ValueError("ROM is too big ({} bytes).".format(totalSize))

            port.write(bytes(f"\n\nmem_load {hex(base)} {totalSize}\n".encode("utf-8")))

            # Send in chunks to display progress
            chunks = [data_bytes[i:i+CHUNK_SIZE] for i in range(0, totalSize, CHUNK_SIZE)]
            print("Sending {} chunks of {} bytes (or less)".format(len(chunks), CHUNK_SIZE))
            sent = 0
            width = len(str(totalSize))
            for chunk in chunks:
                port.write(chunk)
                sent = sent + len(chunk)
                percent = sent*100 / totalSize
                print(f"\rSent: {sent:>{width}} / {totalSize} [{percent:>6.2f}%]", end='')
            print("\nDone.\nSetting ROM header: {}".format(hex(args.header)))

            port.write(bytes(f"set_header {hex(args.header)}\n".encode("utf-8")))
            if args.cic:
                print("Starting CIC")
                port.write(bytes(f"cic\n".encode("utf-8")))
            f.close()

    finally:
        bus.close()

if __name__ == "__main__":
    main()
