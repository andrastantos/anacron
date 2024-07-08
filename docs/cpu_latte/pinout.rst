Pinout
======

Latte is packaged in a 40-pin DIP package. All signals follow the 3.3V CMOS (TTL compatible) standard and are 5V tolerant.

Latte uses a single 5V power supply.

Latte is implemented using the UNiC virtual chip technology.

Latte is design to interface with 72-pin SIMM mdoules with minimal external logic. The data lines are DDR-multiplexed, the address lines are also mostly multiplexed into the same data pins. This allows for very efficient pin utilization.


========== =========== =============== ===========
Pin Number Pin Name    Pin Direction   Description
========== =========== =============== ===========
1          ma0         Output          Multiplexed address bus
2          ma1         Output          Multiplexed address bus
3          ma2         Output          Multiplexed address bus
4          md0         I/O             Data bus
5          md1         I/O             Data bus
6          md2         I/O             Data bus
7          md3         I/O             Data bus
8          md4         I/O             Data bus
9          md5         I/O             Data bus
10         md6         I/O             Data bus
11         md7         I/O             Data bus
12         md8         I/O             Data bus
13         md9         I/O             Data bus
14         md10        I/O             Data bus
15         md11        I/O             Data bus
16         md12        I/O             Data bus
17         md13        I/O             Data bus
18         md14        I/O             Data bus
19         md15        I/O             Data bus
20         GND         GND             Ground input
21         ras0        Output          RAS select
22         ras1        Output          RAS select
23         ras2        Output          RAS select
24         ras4        Output          RAS select
25         n_cas_0     Output          Active low column select, byte 0
26         n_cas_1     Output          Active low column select, byte 1
27         n_cas_2     Output          Active low column select, byte 2
28         n_cas_3     Output          Active low column select, byte 3
29         n_we        Output          Active low write-enable
30         n_rst       Input           Active low reset input
31         n_int       Input           Active low interrupt input
32         n_wait      Input           Active low wait-state input
33         ???         Output          Reserved for bus-sharing hand-shake, if needed
34         dma_req0
35         dma_ack0
36         dma_req1
37         dma_ack1
38         dma_tc
39         sys_clk     Input           Clock input
40         VCC         5V power        Power input
========== =========== =============== ===========

Each RAS bank (0 through 7) can be up to 16MB large. This means 24 address bits. These bits are mapped as follows:

 23  22  21  20  19  18  17  16  15  14  13  12  11  10   9   8   7   6   5   4   3   2   1   0
+---+---+---+---+---+---+---+---+---+---+---+---+---+---+---+---+---+---+---+---+---+---+---+---+
|RAS ma[2:0]|         RAS md[15:8]          |          RAS md[7:0]          |CAS ma[2:0]|  CAS  |
+---+---+---+---+---+---+---+---+---+---+---+---+---+---+---+---+---+---+---+---+---+---+---+---+

Address bits 12...5 (md[7:0]) need to be registered and supplied to the DRAM address bits during
CAS cycles. Address bits 23...13 and 4...2 need tri-state buffers.

Since only the bottom 3 bits of the address can change within a burst, the maximum burst length is
limited to 8 beats, or 32 bytes.

RAS and NREN signals are encoded on 4 pins as follows:

0 - RAS 0
1 - RAS 1
2 - RAS 2
3 - RAS 3
4 - RAS 4
5 - RAS 5
6 - RAS 6
7 - RAS 7
8 - RAS 8
9 - RAS 9
10 - RAS 10
11 - RAS 11
12 - VRAM
13 - NREN
14 - refresh
15 - bus idle

This encoding allows for the use of external pull-ups to idle the bus yet saves 2 extra pins. We probably need an external PAL to decode, but, oh well...

VRAM select video memory (up to 16MB) and NREN selects non-DRAM tragets, such as I/O or ROM. Otherwise they follow the same signal timing as all other RAS banks.

Having 12 RAS banks limits the total addressable DRAM to 192MB with an extra 16MB of video RAM and another 16MB for non-RAM addresses.

What used to be 4 DMA channels on Espresso is now reduced to 2. Not sure how useful they are though...

The corresponding video controller pinout would be as follows:

========== ================ =============== ===========
Pin Number Pin Name         Pin Direction   Description
========== ================ =============== ===========
1          TMDS Data 2+     Output          HDMI/DVI signal
2          TMDS Data 2-     Output          HDMI/DVI signal
3          TMDS Data 1+     Output          HDMI/DVI signal
4          TMDS Data 1-     Output          HDMI/DVI signal
5          TMDS Data 0+     Output          HDMI/DVI signal
6          TMDS Data 0-     Output          HDMI/DVI signal
7          TMDS Clock+      Output          HDMI/DVI signal
8          TMDS Clock-      Output          HDMI/DVI signal
9          ma0              Output          Multiplexed address bus
10         ma1              Output          Multiplexed address bus
11         ma2              Output          Multiplexed address bus
12         md0              I/O             Data bus
13         md1              I/O             Data bus
14         md2              I/O             Data bus
15         md3              I/O             Data bus
16         md4              I/O             Data bus
17         md5              I/O             Data bus
18         md6              I/O             Data bus
19         md7              I/O             Data bus
20         md8              I/O             Data bus
21         md9              I/O             Data bus
22         md10             I/O             Data bus
23         md11             I/O             Data bus
24         md12             I/O             Data bus
25         md13             I/O             Data bus
26         md14             I/O             Data bus
27         md15             I/O             Data bus
28         GND              GND             Ground input
29         ras0             Output          RAS select
30         n_cas            Output          Active low column select, all bytes
31         n_we             Output          Active low write-enable
32         n_rst            Input           Active low reset input
33         n_int            Output          Open-drain, active-low interrupt output
34         n_wait           Output          Active low wait-state input
35         ???              Output          Reserved for bus-sharing hand-shake, if needed
36
37         n_reg_sel        Input           register access select
38         video_clk        Input           Clock input
39         sys_clk          Input           Clock input
40         VCC              5V power        Power input
========== ================ =============== ===========

So, we're missing the audio codec signals. If we don't have those though, we could remove n_we as we won't do writes ever.

Speed considerations
====================

NOTE: this setup doesn't allow for EDO access: only FPM mode is possible. The whole point of EDO is that the data stays active after CAS de-assertion, we we can't do due to our DDR operation.

Given that the external logic interfacing to DRAM adds about 10ns of extra delay per stage (let's hope we only have one), we get the following:

Here's a modern FPM DRAM datasheet: https://www.issi.com/WW/pdf/41LV16105D.pdf here's another (obsolete part): https://datasheet.octopart.com/MT4C1M16C3DJ6-Micron-datasheet-115259.pdf

Finally, here's a rather old and small FPM part: https://tvsat.com.pl/PDF/U/UD61464.pdf

1. 2x10ns decode/buffer delay (one for RAS, one for CAS)
2. 60/70/80/100ns access delay (half for RAS, half for CAS)
3. 10ns slack

We get 90/100/110/130ns cycle time, translating to 11,10,9 and 7.5MHz clock rates respectively.

If we *did* do FPM timing, that's a different story, we could do the following:

1. 10ns decode delay
2. 40ns RAS time
3. 10ns buffer delay
4. 20ns CAS time
5. 10ns buffer delay
6. 20ns CAS time
7. 60ns pre-charge time

Points 3-4 gives us half a cycle, so a 60ns cycle-time is achievable, resulting in a 16MHz clock rate.

OK, so assuming *that*!

And also assuming a 32-byte burst-size, we get:

1 clock cycle for RAS
8 clock cycles for data transfer
1 clock cycle for pre-charge

10 clock cycles gives us 32 bytes, or a transfer rate of over 50MBps. That's substantial!

And 16MHz clock rates should not be out of the realms of possibility for a DIP package. Maybe pushing it a little, but not by much.

So, the architecture here should be:

1. Tiny L1 instruction cache (read only, maybe a direct-map 1kB, line size: 32 bytes).
2. Tiny L1 data cache (write-back, 1kB direct-map, line size: 8 bytes).
3. MMU with 1kB page size and three levels

The data cache might not even be needed, but would certainly help a lot with IPC.