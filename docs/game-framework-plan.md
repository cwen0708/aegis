# 遊戲框架升級規劃

> 從「展示用動態壁紙」到「正式遊戲框架」的路線圖

## 現有架構（5,496 行，20 檔案）

### 2D Phaser（像素藝術）
- OfficeScene.ts (845行)：主場景、角色、攝影機、漫步 AI
- EditorScene.ts (619行)：5 層房間編輯器
- pathfinding.ts (174行)：A* 4 方向尋路
- groundData.ts + furnitureData.ts：100+ 瓷磚 + 傢俱
- 精靈表：128×256，12 動作（walk/sit/work × 4 方向）

### 3D Three.js
- sceneSetup.ts：PerspectiveCamera + ACES + Shadow
- actorManager.ts：5 種 GLB 模型 + 動畫混合
- furnitureManager.ts：GLTF 傢俱 + 程序幾何

### 共用
- CharacterDialog.vue：AVG 對話 + TTS
- 房間 JSON 序列化 + DB 儲存
- 2D/3D 同房間切換

## 缺少的核心系統

### P0：視覺基礎

#### Y-sort 深度排序
- **問題**：角色走到桌子後面不會被遮住
- **方案**：每幀按 `sprite.y + offset` 排序 depth
- **位置**：OfficeScene.ts 的 update loop
- **工作量**：小（~30 行）

#### 碰撞層
- **問題**：角色穿牆、穿傢俱
- **方案**：從 layout 生成碰撞 tilemap，用 Phaser Arcade Physics
- **位置**：新建 collisionLayer + OfficeScene 啟用 physics
- **工作量**：中（~100 行）

### P1：行為基礎

#### 角色狀態機（FSM）
- **問題**：idle/walk/sit/work 硬切換，沒有轉移邏輯
- **方案**：
  ```
  StateMachine
  ├── IdleState：漫步計時 → WalkState
  ├── WalkState：A* 移動 → 到達目標 → SitState / WorkState / IdleState
  ├── SitState：播放坐下動畫 → 等待任務
  └── WorkState：播放工作動畫 → 任務完成 → IdleState
  ```
- **位置**：新建 game/stateMachine.ts
- **工作量**：中（~200 行）

#### Entity 抽象（從 OfficeScene 拆出）
- **問題**：845 行的 OfficeScene 做太多事
- **方案**：
  ```
  Character extends Entity
  ├── SpriteComponent（渲染）
  ├── MovementComponent（尋路 + 碰撞）
  ├── AnimationComponent（狀態機驅動動畫）
  ├── InteractionComponent（點擊事件）
  └── AIComponent（漫步 / 任務指派）
  ```
- **位置**：新建 game/entities/ 目錄
- **工作量**：大（重構 OfficeScene ~400 行）

### P2：互動擴展

#### 事件系統
- **問題**：只有 `character-clicked` 一個事件
- **方案**：通用 EventBus + 觸發區域（trigger zones）
- **事件**：enter-room、approach-desk、task-started、task-completed
- **工作量**：中

#### 音效
- **問題**：只有 TTS，沒有 BGM 和互動音效
- **方案**：Phaser Sound Manager + 音效資產
- **音效**：辦公室環境音、打字聲、通知聲、腳步聲
- **工作量**：小（整合 + 資產）

### P3：進階功能

#### 遊戲內 HUD
- 角色頭上狀態圖示（忙碌/閒置/會議中）
- 浮動任務進度條
- 房間迷你地圖

#### 存檔系統
- 角色位置、朝向、當前狀態持久化
- 房間切換時保留狀態

#### 多人同步（可選）
- WebSocket 即時同步角色位置
- 多用戶同時看到彼此游標

## 實施順序

```
Phase 1（P0）：Y-sort + 碰撞層
  → 視覺不再破綻
  → ~130 行，1-2 天

Phase 2（P1）：狀態機
  → 角色行為可擴展
  → ~200 行，2-3 天

Phase 3（P1）：Entity 抽象
  → OfficeScene 瘦身，架構可維護
  → 重構 ~400 行，3-5 天

Phase 4（P2）：事件 + 音效
  → 互動豐富化
  → ~150 行 + 資產，2-3 天

Phase 5（P3）：HUD + 存檔
  → 完整遊戲體驗
  → 視情況
```

## SkyOffice 分析（2026-03-25）

**位置**：`G:\vendor\SkyOffice\`（MIT 授權）

### 圖片差異

| | SkyOffice | Aegis |
|---|---|---|
| Tile 大小 | **32×32**（原生） | **16×16**（3x 放大 → 模糊） |
| 地板圖集 | `FloorAndGround.png` 2048×1280（2560 tiles） | `room_builder.png` 256×224（~200 tiles） |
| 傢俱圖集 | `Modern_Office_Black_Shadow.png`（848 tiles，帶陰影） | 散裝 PNG（無陰影） |
| 地圖編輯 | **Tiled Map Editor** | 自建 EditorScene |
| 碰撞 | Tiled 設定 `collides: true` → Phaser 原生 | 無碰撞 |
| Y-sort | `item.setDepth(item.y + item.height * 0.27)` | 無 |

### 可直接使用的資產（MIT）

```
client/public/assets/
├── map/FloorAndGround.png       2048×1280  地板+牆壁合併圖集
├── map/map.json                            Tiled 地圖檔（40×30, 11 層）
├── tileset/Modern_Office_Black_Shadow.png  辦公室傢俱（帶陰影）
├── tileset/Generic.png                     通用物品
├── tileset/Basement.png                    地下室風格
├── tileset/Classroom_and_library.png       教室/圖書館
├── items/chair.png                         椅子（23 種）
├── items/computer.png                      電腦（5 種）
└── items/whiteboard.png                    白板（3 種）
```

### 遷移方案

1. 複製 SkyOffice 圖集 + map.json → Aegis assets
2. OfficeScene 改用 `this.load.tilemapTiledJSON()` + `this.make.tilemap()`
3. 碰撞自動帶入（Tiled 已配）
4. EditorScene 暫停使用（改用 Tiled 外部編輯）
5. 座標系調整（16→32 tile）

## 不需要改的

| 元件 | 原因 |
|------|------|
| A* 尋路 | 功能完整，加碰撞層後自動適用 |
| 房間編輯器 | 5 層已夠用 |
| 精靈表系統 | 128×256 + 成員客製已完善 |
| CharacterDialog | AVG 對話 + TTS 已完整 |
| 3D Three.js | 獨立系統，不影響 2D 升級 |
| 房間 JSON 格式 | 向後相容，加新欄位即可 |
