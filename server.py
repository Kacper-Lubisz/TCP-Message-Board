#!/usr/bin/python3.8
"""
This is the server for the Networking Anonymous Board program.  It starts a TCP server which follows the protocol
defined in README.md.
"""
from __future__ import annotations

import sys
import socket
import os
import json
import datetime
import selectors
import threading
import traceback


def parse_args_port(
        ip: str,
        port: str,
        boards_dir: str,
        log_path: str,
        connection_queue: str
) -> (str, int, str, str, int):
    """
    This function is for validating command line arguments.  Each input as strings.  If any parameter is invalid a
    Server error is raised.
    :param ip: The string ipv4 address
    :param port: The string or int of the port number
    :param connection_queue: the string socket connection queue length
    :param log_path: the path to the log file
    :param boards_dir: the path to the directory holding the boards
    :return: (ip, port, board_dir, log_path, connection_queue), The parsed arguments
    :raises: Exception if any argument is erroneous
    """

    try:
        port = int(port)  # this cast will also succeed if the port is of type int
    except ValueError:
        raise ServerException("Port must be a number")

    if port < 0 or port > 65535:
        raise ServerException("Port out of range")

    if ip != "localhost":
        # tests ip pattern, the regex for this is awful
        ip_parts = ip.split(".")
        if len(ip_parts) != 4:
            raise ServerException("Invalid IP")

        def test_ip_section(section):
            """
            Checks if each section of the ip is valid
            :param section: The section to check
            :return: if the section is in range
            :raises: Exception if the ip is in the incorrect format
            """
            try:
                return 0 <= int(section) <= 255
            except ValueError:
                raise ServerException("Invalid IP address")

        if not all(map(test_ip_section, ip_parts)):
            raise ServerException("Invalid IP address")

    # TODO the args below could do with more checks here,
    #  it would be nicer design but not really time effective since the code already throws meaningful errors in these
    #  cases

    if boards_dir.endswith("/"):
        boards_dir = boards_dir[:-1]

    try:
        connection_queue = int(connection_queue)
    except ValueError:
        raise ServerException("Invalid connection queue argument passed, it's must be an integer")

    return ip, port, boards_dir, log_path, connection_queue


class ServerException(Exception):
    """
    This is an error type that the server raises
    """


class Server:
    """
    This class manages the behaviour of the server.  The server object handles requests by creating a thread for each
    connection.  Each of those threads accesses a BufferedReader which allows the protocol to be written in serial
    blocking code.  The server updates all buffered readers when data is available to be read from the socket. The
    protocol that the server operates can be found in README.md
    """

    timeout: float = 5.0
    boards_dir: str = "./boards"
    log_path: str = "./server.log"
    connection_queue: int = 10
    buffer_size: int = 1024 * 16
    version: str = "1.0.0"

    notify_period = 0.1

    def __init__(
            self,
            verbose: bool,
            buffer_size: int,
            boards_dir: str,
            log_file: str,
            connection_queue: int,
            notify_period: float
    ):
        """
        Instantiates a server object
        :param verbose: if the server should print its log to the console
        :param buffer_size: the read buffer size
        :param boards_dir: the path to the boards directory
        :param log_file: the path to the log file
        :param connection_queue: the number of simultaneous unaccepted connections that can queue
        :param notify_period: the period the reader will wait before it begins to acknowledge received data
        """

        self.notify_period = notify_period

        self.verbose = verbose
        self.connection_queue = connection_queue

        self.buffer_size = buffer_size
        self.boards_dir = boards_dir

        self.boards = []

        self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server_socket.settimeout(Server.timeout)

        self.selector = selectors.DefaultSelector()

        self.log_file = log_file

    def __del__(self) -> None:
        self.server_socket.close()
        for key in self.selector.get_map():
            print(">", key)

        self.selector.close()

    def start(self, address: (str, int)) -> None:
        """
        This method starts the server, listening on the specified address
        :param address: The address the server should listen on
        """

        self.load_boards()

        ip, port = address

        try:
            self.server_socket.bind(address)
        except socket.error:
            raise ServerException(f"Port {port} is busy")

        self.server_socket.setblocking(False)
        self.server_socket.listen(self.connection_queue)

        self.write_to_log(
            f"{datetime.datetime.now().isoformat()} {ip.rjust(15)}:{str(port).ljust(5)} Starting Server\n",
            self.verbose
        )

        self.selector.register(self.server_socket, selectors.EVENT_READ, (self.accept_connection, []))

        while True:
            for key, mask in self.selector.select(timeout=.25):
                callback, data = key.data
                callback(*data)

    def accept_connection(self) -> None:
        """
        This method is a callback which processes a new connection being created.  This method is called by the Server
        selector when a new connection is available.  This creates a new ClientConnection object (thread) and registers
        its socket with the selector
        """
        client_socket, address = self.server_socket.accept()
        client = ClientConnection(self, client_socket)

        self.selector.register(
            client_socket,
            selectors.EVENT_READ,
            (client.reader.update, [])
        )

        client.start()

    def unregister(self, client: ClientConnection) -> None:
        """
        This method destroys a ClientConnection object and unregisters it from the selector
        :param client:
        """
        self.selector.unregister(client.socket)
        client.socket.close()

    def process_request(self, request_time: datetime, request_body: dict) -> (str, str, dict):
        """
        This method processes queries and produces the responses, as per protocol described in README.md
        :param request_time: The time at which the request was received
        :param request_body: The query information
        :raises Server.RequestException:  If the request is malformed
        :return: The a tuple representing the request method (? if invalid), the status message and, dictionary response
         to the request
        """

        if "version" not in request_body:
            return "?", "ERROR", {
                "success": False,
                "boards": "No protocol version specified"
            }
        elif request_body["version"] != Server.version:
            return "?", "ERROR", {
                "success": False,
                "boards": f"Incompatible protocol version, server uses {Server.version}"
            }

        if "method" not in request_body:
            return "?", "ERROR", {
                "success": False,
                "boards": "Invalid Request, no method specified"
            }

        method = request_body["method"]  # see README.md
        if method == "GET_BOARDS":

            return method, "OK", {
                "success": True,
                "boards": self.boards
            }

        elif method == "GET_MESSAGES":

            if "board" not in request_body:
                return method, "ERROR", {
                    "success": False,
                    "error": "Argument missing, board: string"
                }

            board_name = request_body["board"].replace(" ", "_")

            try:
                messages = self.load_messages(board_name)
            except FileNotFoundError:
                return method, "ERROR", {
                    "success": False,
                    "error": f"Board '{board_name}' doesn't exist"
                }

            return method, "OK", {
                "success": True,
                "messages": messages
            }

        elif method == "POST_MESSAGE":

            missing_arguments = []
            if "board" not in request_body:
                missing_arguments.append(("board", "string"))
            if "title" not in request_body:
                missing_arguments.append(("title", "string"))
            if "content" not in request_body:
                missing_arguments.append(("content", "string"))

            if len(missing_arguments) != 0:
                missing_string = ", ".join(map(lambda x: f"{x[0]}: {x[1]}", missing_arguments))
                return method, "ERROR", {
                    "success": False,
                    "error": f"Argument(s) missing: {missing_string}"
                }

            try:
                self.write_message_to_file(
                    request_body["board"].replace(" ", "_"),
                    request_time,
                    request_body["title"].replace(" ", "_"),
                    request_body["content"]
                )
                return method, "OK", {
                    "success": True
                }
            except (ServerException, OSError) as exc:
                return method, "ERROR", {
                    "success": False,
                    "error": "Writing message failed, " + str(exc)
                }

        else:
            return "?", "ERROR", {
                "success": False,
                "boards": "Invalid Request, invalid method specified"
            }

    def load_messages(self, board_dir: str) -> list:
        """
        This method loads the messages of a board from the board directory name
        :param board_dir: The name of the directory from which messages are to be read from
        :raises ServerError: if the file system is malformed
        :raises OSError: if a file can't be accessed
        :return: List of messages
        """

        messages = []
        message_files = list(sorted(os.listdir(self.boards_dir + "/" + board_dir), reverse=True))[:100]

        for message_file in message_files:
            message_name_components = message_file.split("-")
            if len(message_name_components) != 3:
                raise ServerException("Invalid message name: " + message_file)
            date, time, title = message_name_components

            with open(self.boards_dir + "/" + board_dir + "/" + message_file) as file:
                contents = file.read()

            messages.append({
                "date": date,
                "time": time,
                "title": title.replace("_", " "),
                "contents": contents
            })

        return messages

    def write_message_to_file(
            self,
            board_dir: str,
            request_time: datetime,
            message_title: str,
            message_content: str
    ) -> None:
        """
        This method stores an instance of a message in the file system.  The message is placed in the boards directory
        inside the corresponding board

        :param board_dir: The name of the subdirectory corresponding to the board that the new message belongs to
        :param request_time: The datetime at the point when the message was received
        :param message_title: The title of the new message
        :param message_content: The content of the new message
        :raises ServerError: if the board doesn't exist
        :raises OSError: if the board file can't be written to
        :return:
        """
        if not os.path.isdir(self.boards_dir + "/" + board_dir):
            raise ServerException(f"Board {board_dir} doesn't exist")

        file_name = request_time.strftime("%Y%m%d-%H%M%S") + "-" + message_title + ""

        with open(self.boards_dir + "/" + board_dir + "/" + file_name, "w") as file:
            file.write(message_content)

    def load_boards(self) -> None:
        """
        This method loads the names of all boards in the define board directory
        :raises ServerException: if the server fails to load boards
        """

        if not os.path.isdir(self.boards_dir):
            raise ServerException(f"{self.boards_dir} doesn't exist")

        for board_dir in os.listdir(self.boards_dir):
            name = board_dir.replace("_", " ")
            self.boards.append(name)

        if len(self.boards) == 0:
            raise ServerException(f"No message boards defined in {self.boards_dir}")

    def write_to_log(self, message, stdout: bool) -> None:
        """
        This method writes a message to the log file, and optionally to the console too
        :param message: The message to be written
        :param stdout: If the message is to also be written to the console
        :raises OSError: if the log file can't be accessed
        """

        with open(self.log_file, "a") as file:
            file.write(message)

        if stdout:
            print(message, end="")


class BufferedReader:
    """
    This class is used for reading from the client socket.  The class maintains its own buffer which is updated when
    data is available and update is called.  This class is used for controlling blocking in reading arbitrary lengths of
    byte array.  It isn't part of ClientConnection so that ClientConnection can implement the protocol as blocking code
    in serial.  The buffered reader also manages sending received acknowledgments to the server.
    """

    def __init__(self, buffer_socket: socket.socket, notify_period: float, read_size: int):
        """
        Instantiates a buffed reader
        :param buffer_socket: The socket which should be buffered
        :param notify_period: the period the reader will wait until it sends received acknowledgments.
        :param read_size: The size of the buffer which is read from the socket in one call to update
        """
        self.socket = buffer_socket
        self.buffer = bytes()
        self.read_size = read_size
        self.notify_period = notify_period

        self.lock_until = 0

        self.read_lock = threading.Lock()
        self.lock = threading.Lock()

        self.last_notified = None

    def read_bytes(self, n):
        """
        This is a blocking method which returns the specified number of bytes from the socket.
        :raises socket.timeout: if the socket times out before the specified number of bytes is read
        """
        with self.lock:
            self.lock_until = n
            if self.lock_until > len(self.buffer):
                self.read_lock.acquire()
                self.last_notified = datetime.datetime.now().timestamp()

        with self.read_lock:
            self.last_notified = None

            data = self.buffer[:n]
            self.buffer = self.buffer[n:]

        return data

    def update(self) -> None:
        """
        This method triggers the buffered reader to read from the socket.  When this is called the buffered reader reads
        its `read_size` more into the buffer.  `read_size` ought to be optimised to maximise speed and fairness between
        concurrent clients.  If adding these bytes to the buffer means that a blocked read_bytes can be unblocked then
        it will be.
        """

        with self.lock:
            read = self.socket.recv(self.read_size)
            self.buffer += read

            if self.read_lock.locked():
                now = datetime.datetime.now().timestamp()
                if now - self.last_notified > self.notify_period:
                    self.last_notified = now

                    self.socket.send(b'\x00\x00\x00\x00\x00\x00\x00\x00')  # acknowledgment
                    self.socket.send((len(self.buffer)).to_bytes(8, "big"))

                if self.lock_until <= len(self.buffer):
                    self.read_lock.release()


class ClientConnection(threading.Thread):
    """
    This class is responsible for implementing the communications part of the protocol specified in README.md.  The
    client connection object is a thread which implements the protocol.  This class uses the blocking buffered reader
    which allows for the protocol to be implemented in series in the run method.
    """

    def __init__(self, server: Server, client_socket: socket.socket):
        """
        Instantiates a new ClientConnection
        :param server: The parent server of the connection
        :param client_socket: The socket of the client that is to be read
        """
        super().__init__(name=str(client_socket.getsockname()))

        self.timestamp = datetime.datetime.now()

        self.server = server
        self.address = client_socket.getsockname()
        self.socket = client_socket

        self.requestSize = None
        self.reader = BufferedReader(client_socket, server.notify_period, server.buffer_size)

    def run(self):
        """
        The thread body which performs the protocol
        :return:
        """

        try:
            request_size = int.from_bytes(self.reader.read_bytes(8), "big")
            request_body = self.reader.read_bytes(request_size)

            request_body = json.loads(request_body.decode())  # throws a json.JSONDecodeError
            method, status, response = self.server.process_request(self.timestamp, request_body)

            request_method = request_body["method"]

        except (socket.timeout, json.JSONDecodeError):
            request_method, status, response = "?", "ERROR", None

        ip, port = self.address

        self.server.write_to_log(
            f"{self.timestamp.isoformat()} {ip.rjust(15)}:{str(port).ljust(5)} {request_method.ljust(12)} {status}\n",
            True
        )

        if response is not None:
            response = json.dumps(response).encode()

            self.socket.send(len(response).to_bytes(8, "big"))
            self.socket.send(response)

        self.server.unregister(self)


def main() -> None:
    """Main function"""

    if sys.version_info[0] < 3 or sys.version_info[1] < 6:
        print("server.py is only compatible with Python 3.6 (or above)")
        sys.exit(1)

    if any(map(lambda flag: flag in sys.argv, ["help", "-h", "--help"])):
        print(
            """usage: server.py [ip] [port]
            options:
            \t-l --log [./server.log] the path to the log file
            \t-b --boards [./boards] the path to the boards directory
            \t-q --queue [10] the number of connections that can queue to be accepted at a time
            \t-v --verbose prints server logs to console
            """)
        sys.exit(0)

    # this loop parses command line arguments and places them into an array
    parsed_args = dict()
    for arg, markers, is_flag in [
        ("log_path", ["-l", "--log"], False),
        ("boards_dir", ["-b", ",--boards"], False),
        ("verbose", ["-v", ",--verbose"], True),
        ("queue", ["-q", ",--queue"], False)
    ]:
        for marker in markers:
            if marker in sys.argv:
                index = sys.argv.index(marker)
                sys.argv.pop(index)

                if not is_flag:
                    parsed_args[arg] = sys.argv[index]
                    sys.argv.pop(index)
                else:
                    parsed_args[arg] = True

    verbose = parsed_args["verbose"] if "verbose" in parsed_args else False
    boards_dir = parsed_args["boards_dir"] if "boards_dir" in parsed_args else Server.boards_dir
    log_path = parsed_args["log_path"] if "log_path" in parsed_args else Server.log_path
    connection_queue = parsed_args["queue"] if "queue" in parsed_args else Server.connection_queue

    ip = sys.argv[1] if len(sys.argv) >= 2 else input("Input IP >")
    port = sys.argv[2] if len(sys.argv) >= 3 else input("Input Port >")

    ip, port, boards_dir, log_path, connection_queue = parse_args_port(ip, port, boards_dir, log_path, connection_queue)
    address = (ip, port)

    # TODO this parsing could do with improving, e.g. in any case where the input args aren't perfect it errors out

    server = Server(verbose, Server.buffer_size, boards_dir, log_path, connection_queue, Server.notify_period)

    try:
        # raise ServerException()
        server.start(address)

    except ServerException:
        timestamp = datetime.datetime.now()
        stack_trace = traceback.format_exc().replace("\n", "\n\t")
        server.write_to_log(
            f"{timestamp.isoformat().ljust(48)} Server Stopped\tException Occurred\n\t{stack_trace}",
            True
        )

    except KeyboardInterrupt:
        timestamp = datetime.datetime.now()
        server.write_to_log(f"{timestamp.isoformat().ljust(48)} Server Stopped\t^C Keyboard Interrupt\n", True)

    finally:
        del server


if __name__ == '__main__':
    try:
        main()
    except Exception as e:
        print("The program failed unexpectedly with message:\n" + str(e))
