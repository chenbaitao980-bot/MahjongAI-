# spectator_forensic.jsonl 分析

总行数: 5904

## msg_type 分布

- S->C 0x2bc0  x3674
- C->S 0x2bc1  x1028
- C->S 0x0018  x271
- S->C 0x0019  x252
- S->C 0x0002  x83
- C->S 0x0002  x80
- C->S 0x0001  x66
- C->S 0x0006  x36
- S->C 0x0001  x35
- C->S 0x000f  x33
- C->S 0x2f1d  x27
- S->C 0x0010  x23
- C->S 0x0003  x22
- C->S 0x620c  x21
- S->C 0x2f1e  x20
- C->S 0x0005  x19
- C->S 0x0017  x19
- S->C 0x0018  x19
- C->S 0x0016  x18
- C->S 0x2c2e  x18
- S->C 0x000a  x18
- S->C 0x0006  x17
- S->C 0x620d  x17
- S->C 0x0004  x16
- S->C 0x0017  x15
- S->C 0x2c2f  x15
- S->C 0x0007  x11
- S->C 0x2c39  x5
- S->C 0x2b01  x4
- S->C 0xc355  x4
- C->S 0x06a7  x4
- S->C 0x06ea  x3
- S->C 0x06a8  x3
- C->S 0x0014  x1
- S->C 0x0015  x1

## 0x2bc0 sub_type 分布

- S->C 0x2bc0/0x0001  x3674

## 0x2bc0 pay_len 分布

- min=9 max=2174 unique={9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 143, 20, 21, 19, 22, 24, 25, 26, 159, 31, 33, 161, 163, 32, 34, 298, 43, 44, 46, 305, 49, 52, 53, 312, 313, 314, 315, 316, 317, 321, 329, 333, 334, 82, 339, 344, 231, 363, 1777, 2174}

## 关键判定

- 这个 forensic 文件**只记录了 frame_head**（没有 raw payload bytes），无法直接判定 hand_raw 是否 0x3c
- 但 0x2BC0 帧确实**真实在线被服务端下发**给 spectator 连接，存在 86 帧
- pay_len 多样（17, 46 等）说明服务端确实在向 spectator 推送游戏内事件流
