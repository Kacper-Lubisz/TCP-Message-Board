#!/usr/bin/python3.8
"""
This is the client for the Networking Anonymous Board program.  It communicates with the server over TCP following the
protocol defined in README.md
"""
from __future__ import annotations

import datetime
import math
import socket
import sys
import json


class ClientException(Exception):
    """
    This is an error type that the client raises
    """
    pass


# this is code that is shared between the client and server. I wasn't certain if it would be a good idea to have a
# separate file with common code in case it messes with any automated marking. I'd suspect it wouldn't.

def read_bytes(
        client_socket: socket.socket,
        n: int,
        buffer_size: int = 1024 * 16,
        timeout: float = 5,
        notify_period: float = .1
):
    """
    This method reads a particular number of bytes from the socket. If this number of bytes can't be read in the
    specified timeout a socket.timeout exception will be raised.  If the specified buffer size is more than the
    number of bytes to read, then the buffer size will be reduced to that amount.

    :param client_socket: The socket to read form
    :param n: The number of bytes to be read
    :param timeout: The time in seconds that the should be waited for
    :param buffer_size: The buffer size used to read from the socket
    :param notify_period: The amount of time that the function will wait to receive the transition before it starts
        printing progress reports
    :return:
    """
    received = bytes()
    buffer = bytes()

    previous_timeout = client_socket.gettimeout()
    client_socket.settimeout(timeout)

    last_notified = datetime.datetime.now().timestamp()

    printed_progress = False
    while len(received) != n and buffer is not None:
        buffer = client_socket.recv(min(buffer_size, n))
        received += buffer

        now = datetime.datetime.now().timestamp()
        if now - last_notified > notify_period:
            last_notified = now
            print(f"Receiving transmission {str(len(received)).rjust(len(str(n)))}/{n} bytes ")
            printed_progress = True

    if printed_progress:
        print("Transmission Complete")

    client_socket.settimeout(previous_timeout)

    return received


def main():
    """Main function"""

    if sys.version_info[0] < 3 or sys.version_info[1] < 6:
        print("server.py is only compatible with Python 3.6 (or above)")
        sys.exit(1)

    if any(map(lambda arg: arg in sys.argv, ["help", "-h", "--help"])):
        print("usage: client.py [ip] [port]\noptions:\n\t-v --verbose prints server logs to console")
        sys.exit(0)

    ip = sys.argv[1] if len(sys.argv) >= 2 else input("Input IP >")
    port = sys.argv[2] if len(sys.argv) >= 3 else input("Input Port >")

    address = parse_ip_port(ip, port)

    # load boards
    response = make_request(address, {
        "method": "GET_BOARDS",
        "version": "1.0.0"
    })

    if not response["success"]:
        raise ClientException(f"The request failed, server responded with the error {response['error']}")
    else:
        print("Successfully loaded boards from the server")

    boards = response["boards"]
    longest_name = max(map(lambda name: len(name), boards))
    longest_index = math.floor(math.log10(len(boards)))

    selection = ""
    while selection != "EXIT":

        print("Type 'EXIT' to exit, 'POST' to post a message or, boards number to view messages")
        for index, board_name in enumerate(boards):
            print(str(index + 1).ljust(longest_index) + ". " + board_name.ljust(longest_name))
            # prints boards

        selection = input(">").upper()

        if selection == "EXIT":
            pass
        elif selection == "POST":  # handles a post
            board_selected = input("Select a board by number >")
            try:
                board_selected = int(board_selected)
            except ValueError:
                print("Invalid board entered")
                continue  # use continue to alleviate crazy indents

            if board_selected <= 0 or board_selected > len(boards):
                print("Invalid board entered")
                continue

            message_title = input("Message title >")
            message_content = input("Message content >")

            # response = make_request(address, {
            #     "method": "POST_MESSAGE",
            #     "version": "1.0.0",
            #     "board": boards[board_selected - 1],
            #     "title": message_title,
            #     "content": message_content
            # })

            for i in range(1001):
                make_request(address, {
                    "method": "POST_MESSAGE",
                    "version": "1.0.0",
                    "board": boards[board_selected - 1],
                    "title": f"message {i + 1}",
                    "content": message_content
                })


            if response["success"]:
                print("Message posted successfully\n")
            else:
                print(f"Posting the message failed, server responded with the error {response['error']}")


        else:  # get messages branch
            try:
                selection = int(selection)
            except ValueError:
                print("Invalid board entered")
                continue

            if selection <= 0 or selection > len(boards):
                print("Invalid board entered")
                continue

            board_messages = make_request(address, {
                "method": "GET_MESSAGES",
                "version": "1.0.0",
                "board": boards[selection - 1]
            })

            if not board_messages["success"]:
                raise ClientException(f"Getting messages failed, server responded with the error {response['error']}")

            messages_number = len(board_messages['messages'])
            plural = '' if messages_number == 1 else 's'
            print(f"Successfully retrieved {messages_number} message{plural} in board '{boards[selection - 1]}'")

            message_count = len(board_messages["messages"])
            for index, message in enumerate(board_messages["messages"]):
                date = datetime.datetime.strptime(message["date"] + message["time"], "%Y%m%d%H%M%S").isoformat()
                print(f"Message {index + 1}/{message_count}\n{message['title']}\n{date}\n{message['contents']}\n")

                selection = input("ENTER for next message, or type 'END' to skip to the end\n>").upper()
                if selection == "END":
                    break


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
        raise ClientException("Port must be a number")

    if port < 0 or port > 65535:
        raise ClientException("Port out of range")

    if ip == "localhost":
        return ip, port

    # tests ip pattern, the regex for this is awful
    ip_parts = ip.split(".")
    if len(ip_parts) != 4:
        raise ClientException("Invalid IP")

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
            raise ClientException("Invalid IP address")

    if not all(map(test_ip_section, ip_parts)):
        raise ClientException("Invalid IP address")

    return ip, port


def make_request(address: (str, int), request_info: dict) -> dict:
    """
    This function makes a request to the back end using a proprietary protocol, see README.md for information.
    :param address:
    :param request_info:
    :return:
    """

    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.connect(address)

        request = json.dumps(request_info).encode()
        request_length = len(request)

        s.send(request_length.to_bytes(8, "big"))
        s.send(request)

        response_size = int.from_bytes(read_bytes(s, 8), "big")

        printed_progress = False
        while response_size == 0:  # acknowledgment
            bytes_read = int.from_bytes(read_bytes(s, 8), "big")
            print(f"Transmitting request, {str(bytes_read).rjust(len(str(request_length)))}/{request_length} bytes ")
            printed_progress = True
            response_size = int.from_bytes(read_bytes(s, 8), "big")

        if printed_progress:
            print("Transmission Complete")

        response = read_bytes(s, response_size).decode()

        s.close()
        return json.loads(response)

    except socket.timeout:
        raise ClientException("The connection with the server timed out")
    except ConnectionRefusedError:
        raise ClientException("Failed to connect")
    except json.decoder.JSONDecodeError:
        raise ClientException("Server sent malformed message")


if __name__ == '__main__':
    try:
        main()

    except KeyboardInterrupt:
        print("^C Keyboard Interrupt, server shutting down")
    except ClientException as client_exception:
        print(f"The program failed with a message: {client_exception}")
    except Exception as e:
        print("The program failed unexpectedly with message:\n" + str(e))
