"""
This is the server for the Networking Anonymous Board program.  It starts a TCP server which follows the protocol
defined in README.md
"""

import sys
import socket
import os
import json
import datetime


def parse_ip_port(ip: str, port: str) -> (str, int):
    """
    This function is for validating ip and port.  Each input as strings.  If the IP address and port are invalid
    then an exception will be raised, otherwise a parsed version will be returned.
    :param ip: The string ipv4 address
    :param port: The string or int of the port number
    :return: (ip, port), The parsed ip and port
    :raises: Exception if ip or port are invalid
    """
    try:
        port = int(port)  # this cast will also succeed if the port is of type int
    except ValueError:
        raise ServerException("Port must be a number")

    if port < 0 or port > 65535:
        raise ServerException("Port out of range")

    if ip == "localhost":
        return ip, port

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

    return ip, port


def main() -> None:
    """Main function"""

    # get ip and port from arguments or input
    if len(sys.argv) == 1:
        print("IP Address and port not passed, example usage 'client.py localhost 3000'")
        ip = input("Input IP >")
        port = input("Input Port >")
    elif len(sys.argv) == 2:
        print("port not passed, example usage 'client.py localhost 3000'")
        ip = sys.argv[1]
        port = input("Input IP >")
    else:
        ip, port = sys.argv[1:]

    address = parse_ip_port(ip, port)

    server = Server()
    server.start(address)


class ServerException(Exception):
    """
    This is an error type that the server raises
    """
    pass


class Server:
    """
    This class manages the behaviour of the server.
    The protocol that the server operates can be found in README.md
    """

    def __init__(
            self,
            buffer_size: int = 1024,
            boards_dir: str = "./boards",
            log_file: str = "server.log"
    ):

        self.buffer_size = buffer_size
        self.boards_dir = boards_dir

        self.boards = []
        self.load_boards()

        self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

        self.log_file = log_file

    def start(self, address: (str, int), connection_queue: int = 100) -> None:
        """
        This method starts the server, listening on the specified address
        :param connection_queue: The number of unaccepted connections that the server should queue before refusing
            connections
        :param address: The address the server should listen on
        """

        ip, port = address

        try:
            self.server_socket.bind(address)
        except socket.error:
            raise ServerException(f"Port {port} is busy")

        self.server_socket.listen(connection_queue)
        print(f"Listening at {ip} on port {port}")

        while True:

            client_socket, address = self.server_socket.accept()
            # client_socket.setblocking(False)
            request_time = datetime.datetime.now()

            try:
                request_size = int.from_bytes(self.read_bytes(client_socket, 4), "big")
                request_body = self.read_bytes(client_socket, request_size)

                request_body = json.loads(request_body.decode())  # throws a json.JSONDecodeError
                method, status, response = self.process_request(request_time, request_body)

                request_method = request_body["method"]

            except (socket.timeout, json.JSONDecodeError):
                request_method, status, response = "?", "ERROR", None

            self.write_to_log(
                f"{address[0]}:{address[1]}\t{request_time.isoformat()}\t{request_method}\t{status}\n",
                True
            )

            if response is not None:
                response = json.dumps(response).encode()

                client_socket.send(len(response).to_bytes(4, "big"))
                client_socket.send(response)

            client_socket.close()

    @staticmethod
    def read_bytes(client_socket: socket.socket, number_of_bytes: int, buffer_size: int = 1024, timeout: float = 5):
        """
        This method reads a particular number of bytes from the socket. If this number of bytes can't be read in the
        specified timeout a socket.timeout exception will be raised.  If the specified buffer size is more than the
        number of bytes to read, then the buffer size will be reduced to that amount.

        :param client_socket: The socket to read form
        :param number_of_bytes: The number of bytes to be read
        :param timeout: The time in seconds that the should be waited for
        :param buffer_size: The buffer size used to read from the socket
        :return:
        """
        received = bytes()
        buffer = bytes()

        previous_timeout = client_socket.gettimeout()
        client_socket.settimeout(timeout)

        while len(received) != number_of_bytes and buffer is not None:
            buffer = client_socket.recv(min(buffer_size, number_of_bytes))
            received += buffer

        client_socket.settimeout(previous_timeout)

        return received

    def process_request(self, request_time: datetime, request_body: dict) -> (str, str, dict):
        """
        This method processes queries and produces the responses, as per protocol described in README.md
        :param request_time: The time at which the request was received
        :param request_body: The query information
        :raises Server.RequestException:  If the request is malformed
        :return: The a touple representing the request method (? if invalid), the status message and dictionary response
         to the request
        """

        if "method" not in request_body:
            return "?", "ERROR", {
                "success": False,
                "boards": "Invalid Request, no method specified"
            }

        method = request_body["method"]
        if method == "GET_BOARDS":  # handles GET_BOARDS requests

            return method, "OK", {
                "success": True,
                "boards": self.boards
            }

        elif method == "GET_MESSAGES":  # handles GET_MESSAGES requests

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

        elif method == "POST_MESSAGE":  # handles POST_MESSAGE requests

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
                    request_body["title"],
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
        message_files = list(reversed(sorted(os.listdir(self.boards_dir + "/" + board_dir))))[:100]

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

    def write_message_to_file(self,
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
            raise ServerException("Board doesn't exist")

        file_name = request_time.strftime("%Y%m%d-%H%M%S") + "-" + message_title + ""

        with open(self.boards_dir + "/" + board_dir + "/" + file_name, "w") as file:
            file.write(message_content)

    def load_boards(self) -> None:
        """
        This method loads the names of all boards in the define board directory
        """

        if not os.path.isdir(self.boards_dir):
            raise Exception(f"{self.boards_dir} doesn't exist")

        for board_dir in os.listdir(self.boards_dir):
            name = board_dir.replace("_", " ")
            self.boards.append(name)

        if len(self.boards) == 0:
            raise Exception("No message boards defined")

    def write_to_log(self, message, print_to_console: bool) -> None:
        """
        This method writes a message to the log file, and optionally to the console too
        :param message: The message to be written
        :param print_to_console: If the message is to also be written to the console
        :raises OSError: if the log file can't be accessed
        """

        with open(self.log_file, "a") as file:
            file.write(message)

        if print_to_console:
            print(message, end="")


if __name__ == '__main__':
    try:
        main()

    except KeyboardInterrupt:
        print("^C Keyboard Interrupt, server shutting down")
    except ServerException as server_exception:
        print(f"The program failed with a message: {server_exception}")
    except Exception as e:
        print("The program failed unexpectedly with message:\n" + str(e))