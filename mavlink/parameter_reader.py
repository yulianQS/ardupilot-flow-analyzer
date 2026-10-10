"""逐个读取，有限重试；不存在的参数保留 N/A。所有调用由串口线程执行。"""
import config

class ParameterReader:
    def __init__(self, link, system, component):
        self.link, self.system, self.component = link, system, component
        self.pending = {}

    def start(self):
        self.pending = {name: [0, 0.0] for name in config.PARAMETERS}

    def received(self, name):
        self.pending.pop(name, None)

    def tick(self, now):
        # 每次最多读两个，避免参数请求挤满遥测链路。
        count = 0
        missing = []
        for name, state in list(self.pending.items()):
            if now - state[1] < config.PARAM_RETRY_S:
                continue
            if state[0] >= config.PARAM_MAX_RETRIES:
                missing.append(name)
                del self.pending[name]
                continue
            self.link.send('param_request_read_send', self.system, self.component, name.encode('ascii'), -1)
            state[0] += 1
            state[1] = now
            count += 1
            if count >= 2:
                break
        return missing
