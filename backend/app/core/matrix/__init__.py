"""Matrix 即時通訊骨架（此 Matrix 指 matrix.org 協議，非 app/core/sync_matrix.py）。

本 package 是 P1-MA-05 Phase 1 Shadow Mode 的基礎。僅提供 client 介面、
資料模型與 NoOp 預設實作，**不含任何網路 I/O**；真實實作（matrix-nio）
留待後續步驟引入。
"""
