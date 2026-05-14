# 文件作用：保存 Agent 的轻量人设草稿状态，包括姓名、当前描述和基础人设配置。


class Scratch:
    def __init__(self, name, currently, config):
        self.name = name
        self.currently = currently
        self.config = config
