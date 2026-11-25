"""Ground station on the OBC debug UART (LPUART1, 115200 8N1): sends each telecommand in TCMDS at its virtual
time (seconds). The firmware's replies are console text, logged as `(lpuart1 <- ground)` / `(lpuart1) ...`."""

TCMDS = [
    (6.0, "CTS1+hello_world()!"),
    (7.0, "CTS1+eps_get_system_status_json()!"),
    (8.0, "CTS1+eps_set_channel_enabled(gnss,1)!"),
    (9.0, "CTS1+eps_get_enabled_channels_json()!"),
    (10.0, "CTS1+eps_get_pbu_housekeeping_data_eng_json()!"),
    (11.0, "CTS1+adcs_identification()!"),
    (12.0, "CTS1+adcs_program_status()!"),
    (13.0, "CTS1+adcs_set_run_mode(1)!"),
    (14.0, "CTS1+adcs_get_current_state_1()!"),
    (15.0, "CTS1+gnss_send_cmd_ascii(log timea once)!"),
    (16.0, "CTS1+fs_write_file_str(hello.txt,CTS-SAT-1 persists)!"),
    (17.0, "CTS1+fs_read_file_hex(hello.txt,0,0)!"),
    (18.0, "CTS1+fs_list_directory(.,0,0)!"),
]


class Peer:
    def __init__(self, ctx):
        self.ctx = ctx
        self.todo = sorted(TCMDS)
        self._arm()

    def _arm(self):
        if self.todo:
            self.ctx.schedule_oneshot_ns(max(1, int(self.todo[0][0] * 1e9) - self.ctx.now_ns))

    def on_timer(self):
        while self.todo and int(self.todo[0][0] * 1e9) <= self.ctx.now_ns:
            cmd = self.todo.pop(0)[1]
            self.ctx.info(f"GROUND TX {cmd}")
            self.ctx.send(cmd.encode() )
        self._arm()

    def on_byte(self, b):
        pass
