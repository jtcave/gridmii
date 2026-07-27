import unittest

from ..neofetch import NeofetchCog, fastfetch_filter

# sample output pulled from a machine with functioning fastfetch
GOOD = """[m[1m[32m         -o          o-[m
[1m[32m          +hydNNNNdyh+[m
[1m[32m        +mMMMMMMMMMMMMm+[m
[1m[32m      `dMM[37mm:[32mNMMMMMMN[37m:m[32mMMd`[m
[1m[32m      hMMMMMMMMMMMMMMMMMMh[m
[1m[32m  ..  yyyyyyyyyyyyyyyyyyyy  ..[m
[1m[32m.mMMm`MMMMMMMMMMMMMMMMMMMM`mMMm.[m
[1m[32m:MMMM-MMMMMMMMMMMMMMMMMMMM-MMMM:[m
[1m[32m:MMMM-MMMMMMMMMMMMMMMMMMMM-MMMM:[m
[1m[32m:MMMM-MMMMMMMMMMMMMMMMMMMM-MMMM:[m
[1m[32m:MMMM-MMMMMMMMMMMMMMMMMMMM-MMMM:[m
[1m[32m-MMMM-MMMMMMMMMMMMMMMMMMMM-MMMM-[m
[1m[32m +yy+ MMMMMMMMMMMMMMMMMMMM +yy+[m
[1m[32m      mMMMMMMMMMMMMMMMMMMm[m
[1m[32m      `/++MMMMh++hMMMM++/`[m
[1m[32m          MMMMo  oMMMM[m
[1m[32m          MMMMo  oMMMM[m
[1m[32m          oNMm-  -mMNs[m
[m===snip===
[m[m[1m[32mu0_a106[m@[1m[32mlocalhost[m
-----------------
[m[1m[32mOS[m: [mAndroid REL 15 armv8l
[m[1m[32mHost[m: [mNVIDIA SHIELD Android TV
[m[1m[32mKernel[m: [mLinux 4.9.141-g9d1bd583388e
[m[1m[32mUptime[m: [m5 days, 17 hours, 28 mins
[m[1m[32mPackages[m: [m139 (dpkg)
[m[1m[32mCPU[m: [mCortex-A57 (4) @ 2.01 GHz
[m[1m[32mMemory[m: [m1.53 GiB / 1.89 GiB ([91m81%[m)
[m[1m[32mSwap[m: [m552.95 MiB / 580.26 MiB ([91m95%[m)
[m[1m[32mDisk (/)[m: [m1.25 GiB / 1.48 GiB ([91m84%[m) - ext4 [Read-only]
[m[1m[32mDisk (/storage/emulated)[m: [m2.79 GiB / 4.96 GiB ([93m56%[m) - fuse
[m[1m[32mLocal IP (wlan0)[m: [m172.16.10.98/24
[m[1m[32mLocale[m: [men_US.UTF-8
"""

# what the filter sees if fastfetch doesn't exist
BAD = "===snip===\n."

class NeofetchTest(unittest.TestCase):
    def test_filter_smoke_test(self):
        filtered = fastfetch_filter(GOOD)
        self.assertIsInstance(filtered, str)

    def test_filter_smoke_test_bad(self):
        filtered = fastfetch_filter(BAD)
        self.assertIsInstance(filtered, str)