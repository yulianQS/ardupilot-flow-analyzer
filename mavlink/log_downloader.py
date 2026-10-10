"""MAVLink 日志协议：有限窗口、按字节覆盖校验、缺口重传及原子完成文件。

串口线程拥有本对象。重复/乱序包不会推进虚假进度；.part 永远不是已完成 BIN。
LOG_ENTRY.size 可能近似，因此长度变化不猜测修复，而报告不完整。
"""
import logging
import time
from pathlib import Path
import config

class LogDownloader:
    def __init__(self, link, system, component, progress, completed, error):
        self.link, self.system, self.component = link, system, component
        self.progress, self.completed, self.error = progress, completed, error
        self.file = None
        self.active = False

    def start(self, log_id, size, directory):
        if self.active:
            raise RuntimeError('已有日志下载正在进行')
        if size <= 0:
            raise ValueError('日志为空或大小无效')
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f'log_{log_id:04d}.BIN'
        suffix = 1
        while path.exists() or path.with_suffix('.BIN.part').exists():
            path = directory / f'log_{log_id:04d}_{suffix}.BIN'
            suffix += 1
        self.path, self.part = path, path.with_suffix('.BIN.part')
        self.file = self.part.open('xb+')
        self.log_id, self.size, self.offset = log_id, size, 0
        self.started = time.monotonic()
        self.active = True
        self.last_report = 0.0
        logging.info('下载开始 id=%s size=%s path=%s', log_id, size, path)
        self._window()

    def _window(self):
        self.length = min(config.LOG_WINDOW_BYTES, self.size - self.offset)
        self.covered = bytearray(self.length)
        self.received_count = 0
        self.retries = 0
        self._request(self.offset, self.length)

    def _request(self, offset, count):
        self.link.send('log_request_data_send', self.system, self.component, self.log_id, offset, count)
        self.last_request = time.monotonic()

    def accept(self, message):
        if not self.active or int(message.id) != self.log_id:
            return
        count = int(message.count)
        if count <= 0 or count > 90 or count > len(message.data):
            return
        start = max(int(message.ofs), self.offset)
        end = min(int(message.ofs) + count, self.offset + self.length)
        if end <= start:
            return
        data_start = start - int(message.ofs)
        self.file.seek(start)
        self.file.write(bytes(message.data[data_start:data_start + end - start]))
        local = start - self.offset
        new_bytes = self.covered[local:local + end - start].count(0)
        self.covered[local:local + end - start] = b'\x01' * (end - start)
        self.received_count += new_bytes
        if new_bytes:
            self.retries = 0
        now = time.monotonic()
        done = self.offset + self.received_count
        if now - self.last_report >= 0.2 or done == self.size:
            self.progress({'done': done, 'total': self.size, 'speed': done / max(now - self.started, 0.001)})
            self.last_report = now
        if self.received_count == self.length:
            self.offset += self.length
            if self.offset == self.size:
                self.file.flush()
                self.file.close()
                self.file = None
                if self.part.stat().st_size != self.size:
                    self.cancel('实际文件大小与预期不一致，日志可能不完整')
                    return
                self.part.rename(self.path)
                self.active = False
                self.link.send('log_request_end_send', self.system, self.component)
                logging.info('下载完整 %s (%s bytes)', self.path, self.size)
                self.completed(str(self.path))
            else:
                self._window()

    def tick(self, now):
        if not self.active or now - self.last_request < config.LOG_RETRY_S:
            return
        self.retries += 1
        if self.retries > config.LOG_MAX_RETRIES:
            self.cancel('下载超时：仍有缺失字节，保留 .part 文件。请重新下载。')
            return
        first = self.covered.index(0)
        end = first
        while end < self.length and self.covered[end] == 0:
            end += 1
        self._request(self.offset + first, end - first)

    def cancel(self, reason='下载已取消，保留 .part 文件'):
        was_active = self.active
        self.active = False
        if self.file:
            self.file.close()
            self.file = None
        if was_active:
            try:
                self.link.send('log_request_end_send', self.system, self.component)
            except Exception:
                logging.exception('无法结束日志传输（连接可能已中断）')
            logging.warning(reason)
            self.error(reason)
