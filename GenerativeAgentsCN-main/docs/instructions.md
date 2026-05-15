## 快速测试，不调用 LLM、不启用向量记忆：

```bash
python start.py --name ww-smoke --no-llm --no-memory
```

## 生成回放

模拟完成后，先压缩数据：

```bash
python compress.py --name ww-demo
```

然后启动回放服务：

```bash
python replay.py
```

```text
http://127.0.0.1:5000/?name=test4
```

可以改成：

```text
http://127.0.0.1:5000/?name=test4&zoom=0.3
```

如果还不够全，再试：

```text
http://127.0.0.1:5000/?name=test4&zoom=0.2
```

或者：

```text
http://127.0.0.1:5000/?name=test4&zoom=0.15
```

`zoom` 越小，看到的地图越大，但角色和文字也会更小。

常用：

```text
局部查看：
http://127.0.0.1:5000/?name=test4&zoom=0.8

较大范围：
http://127.0.0.1:5000/?name=test4&zoom=0.4

接近全貌：
http://127.0.0.1:5000/?name=test4&zoom=0.2
```

另外页面支持用键盘方向键移动镜头：

```text
↑ ↓ ← →
```

所以你可以：

```text
zoom=0.2 + 方向键移动
```

来查看整个小镇地图。