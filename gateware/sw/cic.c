/*

This file is part of ECPKart64.

Copyright (c) 2019 Jan Goldacker
Copyright (c) 2021 Konrad Beckmann <konrad.beckmann@gmail.com>

This is a port of:
https://github.com/jago85/UltraCIC_C/blob/master/cic_c.c

SPDX-License-Identifier: MIT License

Generic CIC implementation for N64
----------------------------------------------------------
This should run on every MCU which is fast enough to
handle the IO operations.
You just have to implement the low level gpio functions:
    - ReadBit() and
    - WriteBit().

Hardware connections
Data Clock Input (DCLK): CIC Pin 14
Data Line, Bidir (DIO):  CIC Pin 15



*/

#include <stdio.h>
#include <string.h>

#include <generated/csr.h>
#include <console.h>

#include "cic.h"

#define DEBUG

// #define INFO(...)
#define INFO(...) printf("\e[92;1mCIC> \e[0m" __VA_ARGS__)

#define REGION_NTSC (0)
#define REGION_PAL  (1)

#define GET_REGION() (REGION_PAL)

/* SEEDs */

// 6102/7101
#define CIC6102_SEED 0x3F

// 6101
#define CIC6101_SEED 0x3F

// 6103/7103
#define CIC6103_SEED 0x78

// 6105/7105
#define CIC6105_SEED 0x91

// 6106/7106
#define CIC6106_SEED 0x85

// 7102
#define CIC7102_SEED 0x3F

/* CHECKSUMs */

// 6102/7101
#define CIC6102_CHECKSUM 0xa, 0x5, 0x3, 0x6, 0xc, 0x0, 0xf, 0x1, 0xd, 0x8, 0x5, 0x9

// 6101
#define CIC6101_CHECKSUM 0x4, 0x5, 0xC, 0xC, 0x7, 0x3, 0xE, 0xE, 0x3, 0x1, 0x7, 0xA

// 6103/7103
#define CIC6103_CHECKSUM 0x5, 0x8, 0x6, 0xf, 0xd, 0x4, 0x7, 0x0, 0x9, 0x8, 0x6, 0x7

// 6105/7105
#define CIC6105_CHECKSUM 0x8, 0x6, 0x1, 0x8, 0xA, 0x4, 0x5, 0xB, 0xC, 0x2, 0xD, 0x3

// 6106/7106
#define CIC6106_CHECKSUM 0x2, 0xB, 0xB, 0xA, 0xD, 0x4, 0xE, 0x6, 0xE, 0xB, 0x7, 0x4

// 7102
#define CIC7102_CHECKSUM 0x4, 0x4, 0x1, 0x6, 0x0, 0xE, 0xC, 0x5, 0xD, 0x9, 0xA, 0xF

static void EncodeRound(unsigned char index);
static void CicRound(unsigned char *);
static void Cic6105Algo(void);

/* Select SEED and CHECKSUM here */
const unsigned char _CicSeed = CIC6102_SEED;
// const unsigned char _CicSeed = CIC6105_SEED;

const unsigned char _CicChecksum[] = {
    CIC6102_CHECKSUM
    // CIC6105_CHECKSUM
};


/* NTSC initial RAM */
const unsigned char _CicRamInitNtsc[] = {
    0xE, 0x0, 0x9, 0xA, 0x1, 0x8, 0x5, 0xA, 0x1, 0x3, 0xE, 0x1, 0x0, 0xD, 0xE, 0xC,
    0x0, 0xB, 0x1, 0x4, 0xF, 0x8, 0xB, 0x5, 0x7, 0xC, 0xD, 0x6, 0x1, 0xE, 0x9, 0x8
};

/* PAL initial RAM */
const unsigned char _CicRamInitPal[] = {
    0xE, 0x0, 0x4, 0xF, 0x5, 0x1, 0x2, 0x1, 0x7, 0x1, 0x9, 0x8, 0x5, 0x7, 0x5, 0xA,
    0x0, 0xB, 0x1, 0x2, 0x3, 0xF, 0x8, 0x2, 0x7, 0x1, 0x9, 0x8, 0x1, 0x1, 0x5, 0xC
};

/* Memory for the CIC algorithm */
unsigned char _CicMem[32];

/* Memory for the 6105 algorithm */
unsigned char _6105Mem[32];

/* YOU HAVE TO IMPLEMENT THE LOW LEVEL GPIO FUNCTIONS ReadBit() and WriteBit() */

static int running = 1;
static int exit_by_uart = 0;

static int check_running(void)
{
    if (!running) {
        return running;
    }

    if (readchar_nonblock()) {
        char c = readchar();
        INFO("Bye! (%02X)\n", c);

        // Stop the CIC
        running = 0;
        exit_by_uart = 1;
    }

    if (n64_cold_reset_in_read() == 0) {
        INFO("Reset detected\n");

        // Stop the CIC
        running = 0;
    }

    return running;
}

static unsigned char ReadBit(void)
{
    unsigned char res;

    unsigned char vin;

    // wait for DCLK to go low
    do {
        vin = n64cic_cic_dclk_in_read();
    } while ((vin & 1) && check_running());

    // Read the data bit
    res = n64cic_cic_dio_in_read();

    // wait for DCLK to go high
    do {
        vin = n64cic_cic_dclk_in_read();
    } while (((vin & 1) == 0) && check_running());

    return res & 0x01;
}

static void WriteBit(unsigned char b)
{
    unsigned char vin;

    // wait for DCLK to go low
    do {
        vin = n64cic_cic_dclk_in_read();
    } while ((vin & 1) && check_running());

    if (b == 0)
    {
        // Drive low
        n64cic_cic_dio_out_write(0);
        n64cic_cic_dio_oe_write(1);
    }

    // wait for DCLK to go high
    do {
        vin = n64cic_cic_dclk_in_read();
    } while (((vin & 1) == 0) && check_running());

    // Disable output
    n64cic_cic_dio_oe_write(0);
}

/* Writes the lowes 4 bits of the byte */
static void WriteNibble(unsigned char n)
{
    WriteBit(n & 0x08);
    WriteBit(n & 0x04);
    WriteBit(n & 0x02);
    WriteBit(n & 0x01);
}

// Write RAM nibbles until index hits a 16 Byte border
static void WriteRamNibbles(unsigned char index)
{
    do
    {
        WriteNibble(_CicMem[index]);
        index++;
    } while ((index & 0x0f) != 0);
}

/* Reads 4 bits and returns them in the lowes 4 bits of a byte */
static unsigned char ReadNibble(void)
{
    unsigned char res = 0;
    unsigned char i;
    for (i = 0; i < 4; i++)
    {
        res <<= 1;
        res |= ReadBit();
    }
    return res;
}

/* Encrypt and output the seed */
static void WriteSeed(void)
{
    _CicMem[0x0a] = 0xb;
    _CicMem[0x0b] = 0x5;
    _CicMem[0x0c] = _CicSeed >> 4;
    _CicMem[0x0d] = _CicSeed;
    _CicMem[0x0e] = _CicSeed >> 4;
    _CicMem[0x0f] = _CicSeed;

    EncodeRound(0x0a);
    EncodeRound(0x0a);

#ifdef DEBUG

    unsigned char index = 0x0a;
    printf("Seed: ");
    do
    {
        printf("%X ", (_CicMem[index]));
        index++;
    } while ((index & 0x0f) != 0);
    printf("\n");

#endif


    WriteRamNibbles(0x0a);
}

/* Encrypt and output the checksum */
static void WriteChecksum(void)
{
    unsigned char i;
    for (i = 0; i < 12; i++)
        _CicMem[i + 4] = _CicChecksum[i];

    // wait for DCLK to go low
    // (doesn't seem to be necessary)
    // int vin;
    // do {
    //     vin = n64cic_cic_dclk_in_read();
    // } while ((vin & 1) && check_running());

    // "encrytion" key
    // initial value doesn't matter
    //_CicMem[0x00] = 0;
    //_CicMem[0x01] = 0xd;
    //_CicMem[0x02] = 0;
    //_CicMem[0x03] = 0;

    EncodeRound(0x00);
    EncodeRound(0x00);
    EncodeRound(0x00);
    EncodeRound(0x00);

#ifdef DEBUG

    unsigned char index = 0;
    printf("Checksum: ");
    do
    {
        printf("%X ", (_CicMem[index]));
        index++;
    } while ((index & 0x0f) != 0);
    printf("\n");

#endif

    // signal that we are done to the pif
    // (test with WriteBit(1) also worked)
    WriteBit(0);

    // Write 16 nibbles
    WriteRamNibbles(0);
}

/* seed and checksum encryption algorithm */
static void EncodeRound(unsigned char index)
{
    unsigned char a;

    a = _CicMem[index];
    index++;

    do
    {
        a = (a + 1) & 0x0f;
        a = (a + _CicMem[index]) & 0x0f;
        _CicMem[index] = a;
        index++;
    } while ((index & 0x0f) != 0);
}

/* Exchange value of a and b */
static void Exchange(unsigned char *a, unsigned char *b)
{
    unsigned char tmp;
    tmp = *a;
    *a = *b;
    *b = tmp;
}

// translated from PIC asm code (thx to Mike Ryan for the PIC implementation)
// this implementation saves program memory in LM8

/* CIC compare mode memory alternation algorithm */
static void CicRound(unsigned char * m)
{
    unsigned char a;
    unsigned char b, x;

    x = m[15];
    a = x;

    do
    {
        b = 1;
        a += m[b] + 1;
        m[b] = a;
        b++;
        a += m[b] + 1;
        Exchange(&a, &m[b]);
        m[b] = ~m[b];
        b++;
        a &= 0xf;
        a += (m[b] & 0xf) + 1;
        if (a < 16)
        {
            Exchange(&a, &m[b]);
            b++;
        }
        a += m[b];
        m[b] = a;
        b++;
        a += m[b];
        Exchange(&a, &m[b]);
        b++;
        a &= 0xf;
        a += 8;
        if (a < 16)
            a += m[b];
        Exchange(&a, &m[b]);
        b++;
        do
        {
            a += m[b] + 1;
            m[b] = a;
            b++;
            b &= 0xf;
        } while (b != 0);
        a = x + 0xf;
        x = a & 0xf;
    } while (x != 15);
}

// Big Thx to Mike Ryan, John McMaster, marshallh for publishing their work

/* CIC 6105 algorithm */
static void Cic6105Algo(void)
{
    unsigned char A = 5;
    unsigned char carry = 1;
    unsigned char i;
    for (i = 0; i < 30; ++i)
    {
        if (!(_6105Mem[i] & 1))
            A += 8;
        if (!(A & 2))
            A += 4;
        A = (A + _6105Mem[i]) & 0xf;
        _6105Mem[i] = A;
        if (!carry)
            A += 7;
        A = (A + _6105Mem[i]) & 0xF;
        A = A + _6105Mem[i] + carry;
        if (A >= 0x10)
        {
            carry = 1;
            A -= 0x10;
        }
        else
        {
            carry = 0;
        }
        A = (~A) & 0xf;
        _6105Mem[i] = A;
    }
}

/* CIC compare mode */
static void CompareMode(unsigned char isPal)
{
    unsigned char ramPtr;
    // don't care about the low ram as we don't check this
//  CicRound(&_CicMem[0x00]);
//  CicRound(&_CicMem[0x00]);
//  CicRound(&_CicMem[0x00]);

    // only need to calculate the high ram
    CicRound(&_CicMem[0x10]);
    CicRound(&_CicMem[0x10]);
    CicRound(&_CicMem[0x10]);

    // 0x17 determines the start index (but never 0)
    ramPtr = _CicMem[0x17] & 0xf;
    if (ramPtr == 0)
        ramPtr = 1;
    ramPtr |= 0x10;

    do
    {
        // read the bit from PIF (don't care about the value)
        ReadBit();

        // send out the lowest bit of the currently indexed ram
        WriteBit(_CicMem[ramPtr] & 0x01);

        // PAL or NTSC?
        if (!isPal)
        {
            // NTSC
            ramPtr++;
        }
        else
        {
            // PAL
            ramPtr--;
        }

        // repeat until the end is reached
    } while (ramPtr & 0xf);
}

/* CIC 6105 mode */
static void Cic6105Mode(void)
{
    unsigned char ramPtr;

    // write 0xa 0xa
    WriteNibble(0xa);
    WriteNibble(0xa);

    // receive 30 nibbles
    for (ramPtr = 0; ramPtr < 30; ramPtr++)
    {
        _6105Mem[ramPtr] = ReadNibble();
    }

    // execute the algorithm
    Cic6105Algo();

    // send bit 0
    WriteBit(0);

    // send 30 nibbles
    for (ramPtr = 0; ramPtr < 30; ramPtr++)
    {
        WriteNibble(_6105Mem[ramPtr]);
    }
}

/* Load initial ram depending on region */
static void InitRam(unsigned char isPal)
{
    unsigned char i;

    if (!isPal)
    {
        for (i = 0; i < 32; i++)
            _CicMem[i] = _CicRamInitNtsc[i];
    }
    else
    {
        for (i = 0; i < 32; i++)
            _CicMem[i] = _CicRamInitPal[i];
    }
}

static void cic_run(void)
{
    unsigned char isPal;

    // Reset the state
    memset(_CicMem, 0, sizeof(_CicMem));
    memset(_6105Mem, 0, sizeof(_6105Mem));
    running = 1;
    exit_by_uart = 0;

    n64cic_cic_dio_oe_write(0);

    INFO("Waiting for reset... Press any key to exit.\n");
    // Wait for reset to be released
    while (n64_cold_reset_in_read() == 0) {
        if (readchar_nonblock()) {
            readchar();
            exit_by_uart = 1;
            return;
        }
    }
    INFO("Let's-a-go!\n");

    // read the region setting
    isPal = GET_REGION();

    // send out the corresponding id
    unsigned char hello = 0x1;
    if (isPal)
        hello |= 0x4;

    // printf("W: %02X\n", hello);
    WriteNibble(hello);

    // encode and send the seed
    WriteSeed();

    // encode and send the checksum
    WriteChecksum();

    // init the ram corresponding to the region
    InitRam(isPal);

    // read the initial values from the PIF
    _CicMem[0x01] = ReadNibble();
    _CicMem[0x11] = ReadNibble();

    INFO("Entering loop\n");

    while(check_running())
    {
        // read mode (2 bit)
        unsigned char cmd = 0;
        cmd |= (ReadBit() << 1);
        cmd |= ReadBit();
        switch (cmd)
        {
        case 0:
            // 00 (compare)
            CompareMode(isPal);
            break;

        case 2:
            // 10 (6105)
            Cic6105Mode();
            break;

        case 3:
            // 11 (reset)
            WriteBit(0);
            break;

        case 1:
            // 01 (die)
        default:
            return;
        }
    }

    n64cic_cic_dio_oe_write(0);
    INFO("Killed!\n");
}

void main_cic(void)
{
    INFO("Starting CIC.\n");
    do {
        cic_run();
    } while(exit_by_uart == 0);
}
