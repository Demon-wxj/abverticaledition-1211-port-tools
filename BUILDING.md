# 迁移与检查

准备 Python 3，并将以下合法取得的输入放入 `inputs/`：

- `abverticaledition-1.0.3b-fabric-mc1.20.jar`：原 Mod。
- `VerticalBlockType.java`：上游材料定义，属于 ARR，不随仓库提供。
- `minecraft-client.jar`：Minecraft 1.21.1 客户端 JAR，用于读取原版方块标签。
- `stone-resources/`：Stone Edition 的迁移资源，用于配套材料的配方和挖掘标签。

在仓库根目录运行：

```powershell
python tools/port_resources.py migrate --jar inputs/abverticaledition-1.0.3b-fabric-mc1.20.jar --resources output/resources --report output/resource-port-report.json --source inputs/VerticalBlockType.java --companion-resources inputs/stone-resources --vanilla-jar inputs/minecraft-client.jar
python tools/port_resources.py check --resources output/resources --report output/resource-port-report.json --source inputs/VerticalBlockType.java
```

迁移资源写入 `output/resources/`，文件清单写入 `output/resource-port-report.json`，原 JAR 不变。`check` 检查数据格式、本地模型引用、配方、掉落表条件和清单哈希，不检查游戏运行。

当前脚本的迁移步骤需要以上全部输入，即使只打算使用基础材料，也不能省略 Stone 配套资源。这里没有上游 Java 构建工程，不能编译完整 Mod；资源迁移也不会授予 ARR 内容的再分发权限。
