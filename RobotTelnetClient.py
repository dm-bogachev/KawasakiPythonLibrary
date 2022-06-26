import time
from telnetlib import DO, ECHO, IAC, SB, SE, TTYPE, WILL, Telnet
from threading import Thread


class RobotTelnetClient(Thread):
    __LOGIN_REQUEST = b'login:'
    __TELNET_PROMPT = b'>'
    __ENDLINE = b'\r\n'

    def __connect__(self):
        print(f'Connecting to: {self.ip}:{self.port}')
        self.telnet = Telnet()
        self.telnet.set_option_negotiation_callback(
            self.__option_negotiation_callback)
        try:
            self.telnet.open(self.ip, self.port, self.timeout)
            time.sleep(0.5)
            _ = self.telnet.read_until(self.__LOGIN_REQUEST)
            print(_)
            self.telnet.write(self.user.encode() + self.__ENDLINE)
            _ = self.telnet.read_until(self.__TELNET_PROMPT)
            print(_)
        except Exception as msg:
            print(msg)
            self.telnet.close()
            print("Connection failed")
            return
        print("Connection successfully established")
        self.connected = True

    # Method was stolen from https://github.com/BustinBalls/AutonomousBilliards/blob/3c5f1b93d69423dd8a7d08489cb1903c9e57952a/FullCycle.py
    def __option_negotiation_callback(self, socket, cmd, opt):
        IS = b'\00'
        if cmd == WILL and opt == ECHO:  # hex:ff fb 01 name:IAC WILL ECHO description:(I will echo)
            socket.sendall(
                IAC + DO + opt
            )  # hex(ff fd 01), name(IAC DO ECHO), descr(please use echo)
        elif cmd == DO and opt == TTYPE:  # hex(ff fd 18), name(IAC DO TTYPE), descr(please send environment type)
            socket.sendall(
                IAC + WILL + TTYPE
            )  # hex(ff fb 18), name(IAC WILL TTYPE), descr(Dont worry, i'll send environment type)
        elif cmd == SB:
            socket.sendall(IAC + SB + TTYPE + IS + self.env_term.encode() +
                           IS + IAC + SE)
            # hex(ff fa 18 00 b"VT100" 00 ff f0) name(IAC SB TTYPE iS VT100 IS IAC SE) descr(Start subnegotiation, environment type is VT100, end negotation)
        elif cmd == SE:  # server letting us know sub negotiation has ended
            pass  # do nothing
        else:
            print('Unexpected telnet negotiation')

    def __init__(self, ip='192.168.0.2', port=23, timeout=5, user="as"):
        super().__init__()
        self.ip = ip
        self.port = port
        self.timeout = timeout
        self.user = "as"
        self.stop_flag = False
        self.connected = False
        self.save_request = False
        self.load_request = False
        self.start()

    def __check_command(self, command):
        if 'save' in command:
            self.save_request = True
            self.sl_filename = command.split(' ')[-1]
            return False
        if 'load' in command:
            self.load_request = True
            self.sl_filename = command.split(' ')[-1]
            return False
        if 'exec' in command:
            return False
        return True

    def send_command(self, command):
        if not self.__check_command(command): return
        _ = self.telnet.read_eager()  #self.__TELNET_PROMPT, 1)
        self.telnet.write(command.encode() + self.__ENDLINE)

        bytes = self.telnet.read_until(self.__ENDLINE, timeout=1)
        bytes = bytes + self.telnet.read_until(self.__TELNET_PROMPT, timeout=1)
        if b'Yes:1, No:0' in bytes:
            self.telnet.write(b'1' + self.__ENDLINE)
            bytes = bytes + self.telnet.read_until(self.__ENDLINE, timeout=1)
            bytes = bytes + self.telnet.read_until(self.__TELNET_PROMPT,
                                                   timeout=1)
        response = bytes.decode().split('\r\n')

        return response

    def run(self):
        self.__connect__()
        while not self.stop_flag:
            a = 0
            if self.save_request:
                self.__save_as_file(self.sl_filename)
                self.save_request = False
            if self.load_request:
                self.__load_as_file(self.sl_filename)
                self.load_request = False

    def __load_bytes(self, content_split):
        self.telnet.write(b"load master.as\r\n")
        self.telnet.read_until(b".as").decode("ascii")
        self.telnet.write(b"\x02A    0\x17")
        self.telnet.read_until(b"\x17")
        for i in range(0, len(content_split), 1):
            self.telnet.write(b"\x02C    0" + content_split[i] + b"\x17")
            self.telnet.read_until(b"\x17")
        self.telnet.write(b"\x02" + b"C    0" + b"\x1a\x17")
        self.telnet.write(b"\r\n")
        self.telnet.read_until(b"E\x17")
        self.telnet.write(b"\x02" + b"E    0" + b"\x17")
        self.telnet.read_until(b">")

    def __load_as_file(self, file_location='default.as'):
        max_chars = 492
        print(f'Loading {file_location}')
        file = open(file_location, 'r')
        content = file.read()
        content_split = [
            content[i:i + max_chars].encode()
            for i in range(0, len(content), max_chars)
        ]
        self.__load_bytes(content_split)
        print('File load completed')

    def __save_bytes(self):
        self.telnet.write(b"save file.as\r\n")
        self.telnet.read_until(b".as").decode("ascii")
        self.telnet.write(b"\x02B    0\x17")
        message = True
        raw_bytes = b''
        while True:
            if message:
                bytes = self.telnet.read_until(b'\x05\x02')
                raw_bytes = raw_bytes + bytes
                bytes = self.telnet.read_eager()
                raw_bytes = raw_bytes + bytes
                if b'E\x17' in bytes:  # == b'\x45':
                    break
            else:
                bytes = self.telnet.read_until(b'\x17')
                raw_bytes = raw_bytes + bytes
            message = not message
        self.telnet.write(b"\x02\x45" + b"    0" + b"\x17")
        self.telnet.write(b"\r\n")
        self.telnet.write(b"\x02" + b"E    0" + b"\x17")
        bytes = self.telnet.read_until(b">")

        return raw_bytes

    def __parse_raw_bytes(self, bytes):
        lines = bytes.split(b'\r\n')
        result = []
        for i in range(len(lines)):
            line = lines[i]
            if line.startswith(b'\x05\x02D'):
                line = line.replace(b'\x05\x02D', b'')
            if line.startswith(b'\x17\x05\x02D'):
                line = line.replace(b'\x17\x05\x02D', b'')
            if line.startswith(b'\x17'):
                line = b''
            if line.startswith(b'\x05\x02B'):
                line = b''
            if line != b'':
                result.append((line + b'\n').decode())
        return result

    def stop(self):
        self.stop_flag = True

    def __save_as_file(self, file_location='default.as'):
        print(f'Saving {file_location}')
        bytes = self.__save_bytes()
        text = self.__parse_raw_bytes(bytes)
        try:
            file = open(file_location, "w")
            file.writelines(text)
            file.close()
        except Exception as msg:
            pass
        print("File save completed")


#Lastknown check, was built and sent to robot#still True [yes] [no]

if __name__ == '__main__':
    robot = RobotTelnetClient(ip='192.168.0.3', port=9105)
    while not robot.connected:
        pass
    while True:
        _ = input('::')
        if _ == 'q':
            robot.telnet.close()
            robot.stop()
            break
        response = robot.send_command(_)
        if response is not None:
            for i in response:
                print(i + '\n')
    print('finishedq')
