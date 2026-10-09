# 构建与迁移

本仓库不是上游 Mod 的可构建源码包，没有上游 Java 源码、JAR 或美术。仅需 Python 3 标准库。先合法取得原文件并放入 `inputs/`。

```powershell
python tools/port_resources.py migrate --jar inputs/abverticaledition-1.0.3b-fabric-mc1.20.jar --resources output/resources --report output/resource-port-report.json --source inputs/VerticalBlockType.java --companion-resources inputs/stone-resources
python tools/port_resources.py check --resources output/resources --report output/resource-port-report.json --vanilla-jar inputs/minecraft-client.jar
```

`migrate` 只在指定资源输出目录写入迁移结果；原 JAR 不变。`check` 的完整原版纹理引用检查需提供你合法持有的 Minecraft 客户端 JAR。资源迁移不意味着取得公开再分发上游资源的授权。

脚本读取上游 VerticalBlockType.java 的材料定义；该 ARR 文件必须由你自行取得，不能由此仓库提供。可选 Stone 扩展还需要你自己的 Stone 迁移资源。没有这些输入，不能宣称完整迁移或组合验证通过。
