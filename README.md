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
