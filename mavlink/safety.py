"""唯一发送入口。不提供 COMMAND_LONG、参数写入、模式切换或执行器接口。"""
class ReadOnlyLink:
    ALLOWED = frozenset({'request_data_stream_send', 'param_request_read_send',
                         'log_request_list_send', 'log_request_data_send',
                         'log_request_end_send', 'autopilot_version_request_send'})

    def __init__(self, connection):
        self._connection = connection

    def send(self, method, *arguments):
        if method not in self.ALLOWED:
            raise PermissionError(f'只读策略拒绝发送: {method}')
        getattr(self._connection.mav, method)(*arguments)
