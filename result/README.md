# Background

We tried to use push&pop method to speed up the minesweeper but failed.

Here is some result and analysis.

# Data

| configuration                         | bics_ospf | bics_bgp   |
| ------------------------------------- | :-------: | ---------- |
| **router num**                        |    33     | 49         |
| **config2spec time(mf1, from paper)** |  38.8 s   | 68.3 s     |
| **full verification time**            | 854.81 s  | 8961.80 s  |
| **variables num**                     |   1690    | 6982       |
| **constraints num**                   |   3564    | 9620       |
| **incremental verification time**     | 1816.44 s | 11836.03 s |
| **variables num**                     |   2490    | 8758       |
| **constraints num**                   |   5449    | 12788      |

# Conclusion

- The nature of push&pop method is making full use of caching. However, It is not proper to put hope on z3.
- The push&pop method reduce the time of encoding constraint time while increase the number of constraints and increase the time of solve the constraints.
- The non-incremental mode of z3 can leverage much more powerful pre-processing.
- The non-incremental bit-vector solver is usually faster.However, for linear integer arithmetic, the incremental solver seems to work very well.

