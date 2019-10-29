import socket  # Import socket module
import time  # Import time module
import datetime
import os
import p2putils
import select
import sys
from builtins import input
from tkinter import filedialog, Tk

"""
Depends on: 
1. pip install future - For Python 2,3 Compatibility 
"""


class Client:
    """
    The constructor for the class Client
    """

    def __init__(self, udp_port):
        self.ip = "127.0.0.1"

        # clients udp port
        self.port = udp_port

        print("Created Client - {} : {}".format(self.ip, self.port))

        while True:
            try:
                command = input("Please enter a command: r = receive file, s = send file, x = quit\n")

                if command == "x":
                    break

                elif command == "r":
                    self.receive_file()

                elif command == "s":
                    root = Tk()
                    root.filename = filedialog.askopenfilename(title="Select file")
                    file_path = os.path.abspath(root.filename)
                    root.destroy()

                    if not file_path or (not os.path.exists(file_path)) or (not os.path.isfile(file_path)):
                        print("Path is invalid or path is a folder, please try send command again")
                        continue

                    dest_ip = self.ip

                    try:
                        dest_port = int(input("Please enter the destination port: "))
                    except(ValueError, Exception) as porterr:
                        print("Invalid port, please try send command again; err: {}".format(porterr))
                        continue

                    print("File: {} - Size: {}".format(file_path, os.stat(file_path).st_size))
                    print("Sending File in 5 seconds")
                    time.sleep(5)
                    self.send_file(file_path, dest_ip, self.port, dest_port)

                else:
                    print("Please enter a proper command!")

            except KeyboardInterrupt:
                pass

            except() as e:
                print("err: {}".format(e))

    def receive_file(self):
        expected_seq_num = 0
        file_name = ""

        tsocket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        tsocket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        tsocket.bind(('', self.port))

        print("Receiver: Listening on {} : {}".format(self.ip, self.port))
        print("Waiting for Filename...")
        while True:
            try:
                ready = select.select([tsocket], [], [], p2putils.transfer_timeout)
                # print("Data for ready: {}".format(ready))

                if ready[0]:
                    # get filename from sender
                    data_recv2, rsconn2 = tsocket.recvfrom(p2putils.receive_buffer)
                    file_name = data_recv2.decode('utf8')

                    print("Received filename: {}".format(file_name))
                    print("Sending OK to continue")
                    tsocket.sendto(b"OK", rsconn2)
                    break

                # if no response within timeout skip
                else:
                    continue

            except socket.error as err:
                print("Socket err: {}".format(err))
                return

            except KeyboardInterrupt:
                print("\nReceiver: Shutting down")
                return

        """     Start receiving packets for file     """
        start_receive_time = datetime.datetime.now()

        # Open output file
        try:
            fd = open(file_name, "wb")
        except():
            print("Failed to open file: {}".format(file_name))
            sys.exit(-1)

        print("Receiver: Waiting for data...")
        while True:
            try:
                ready = select.select([tsocket], [], [], p2putils.transfer_timeout)
                # print("Data for ready: {}".format(ready))

                if ready[0]:
                    upacket_recv, sconnection = tsocket.recvfrom(p2putils.receive_buffer)
                    print("Receiver: Packet received from: {}".format(sconnection))

                elif expected_seq_num == 0:
                    # print("Receiver: No data yet")
                    continue

                # if no response within 4 seconds close receiver
                else:
                    print("Receiver: Connection timeout err: {} second(s)".format(p2putils.transfer_timeout))
                    tsocket.close()
                    fd.close()
                    break

            except socket.error as esocrr:
                print("Socket err: {}".format(esocrr))
                # print("Receiver: Socket error, dropping pkt")
                continue

            except KeyboardInterrupt:
                print("\nReceiver: Shutting down")
                tsocket.close()
                fd.close()
                break

            upacket_unpacked = p2putils.unpack_packet(upacket_recv)

            # if this is the confirmation packet for all packets received, close and exit receiver
            if upacket_unpacked[3] == -1:
                end_receive_time = datetime.datetime.now()

                print("Receiver: Received Confirmation Packet: {}".format(upacket_unpacked))
                print("Receiver: All Packets Received, File Received Successfully!")
                print("Receiver: Time Taken - {}\n".format(end_receive_time - start_receive_time))

                tsocket.close()
                fd.close()
                break

            print("Receiver: Received packet: {}".format(upacket_unpacked))

            # Compute checksum
            upacket_chksum = upacket_unpacked[2]
            client_computed_chksum = p2putils.checksum2(upacket_unpacked[-1])
            print("Checking checksum: {} - {}".format(upacket_chksum, client_computed_chksum))

            if upacket_chksum != client_computed_chksum:
                print("Receiver: Invalid checksum, packet dropped\n")
                continue

            # Check sequence number
            print("Checking sequence number: {} - {}".format(upacket_unpacked[3], expected_seq_num))
            if expected_seq_num != upacket_unpacked[3]:
                print("Receiver: Unexpected sequence number: {} - expected: {}\n".format(upacket_unpacked[3],
                                                                                         expected_seq_num))
                continue

            # Send ACK
            print("Receiver: Sending ack to: {}\n".format(sconnection))
            tsocket.sendto(p2putils.pack_ack(upacket_unpacked), sconnection)
            expected_seq_num += 1

            # Write data to file
            try:
                _data = upacket_unpacked[-1]
                print("Data: {}".format(_data))

                fd.write(_data)

            except():
                print("Failed to open file: {}".format(file_name))

    def send_file(self, file_path, ip, src_port, dest_port):
        tsocket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        tsocket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        tsocket.bind(('', self.port))

        resend_try_count = 0
        max_resend_count = 10

        file_pathtrim = os.path.basename(file_path)
        (_filename, _file_extension) = os.path.splitext(file_pathtrim)

        file_name = (_filename + "_tr") + _file_extension

        print("Sending filename: {}".format(file_name))
        tsocket.sendto(bytes(file_name, 'utf8'), (ip, dest_port))

        start_send_time = datetime.datetime.now()

        # wait till we get the number to calculate
        print("Sender: Waiting for OK...")
        while True:
            try:
                ready = select.select([tsocket], [], [], p2putils.transfer_timeout)

                if ready[0]:
                    data_recv, rsconn = tsocket.recvfrom(p2putils.receive_buffer)

                    print("\nGot receiver response: {}".format(data_recv))
                    print("Continuing!")
                    break

                # if no response within timeout skip
                else:
                    continue

            except socket.error as err:
                print("Socket err: {}".format(err))
                tsocket.close()
                return

            except KeyboardInterrupt:
                print("\nSender: Shutting down")
                tsocket.close()
                return

        # Build packet list
        upackets = p2putils.read_file(file_path, src_port, dest_port)

        print("\nNumber of Packets to Send: {}\n".format(len(upackets)))

        # packet list index number
        upacket_seq_num = 0

        # number to keep track of the number of packets sent out that need acknowledgment
        upacket_ack_count = 0

        while upacket_seq_num < len(upackets):

            # if the previous packet was acknowledged, then this if will get executed
            # Can we send a packet, do we need to send pkt
            if upacket_ack_count < 1 and (upacket_ack_count + upacket_seq_num) < len(upackets):
                tsocket.sendto(upackets[upacket_seq_num + upacket_ack_count], (ip, dest_port))
                print("Sender: Sent packet to: {} : {}".format(ip, str(dest_port)))
                upacket_ack_count += 1
                continue

            # if we haven't gotten an acknowledgment from the server on the
            # last packet we've sent then the above if won't be executed, which means that we need
            # to listen for an acknowledgment of the sequence number of the last packet
            else:
                try:
                    # Listen for ACKs
                    ready = select.select([tsocket], [], [], p2putils.transfer_timeout)

                    if ready[0]:
                        upacket_recv, sconnection = tsocket.recvfrom(p2putils.receive_buffer)
                        print("Sender: Packet received from: {}".format(sconnection))

                    else:
                        # no ACK received before timeout
                        print("Sender: No packet received before timeout: {} - seq_num: {} - try: {}\n"
                              .format(p2putils.transfer_timeout, upacket_seq_num, resend_try_count))

                        if resend_try_count >= max_resend_count:
                            print("Max packet resend count hit, shutting down file transfer")
                            tsocket.close()
                            return

                        upacket_ack_count = 0
                        resend_try_count += 1
                        continue

                    # unpack packet
                    upacket_ack_seqnum = p2putils.unpack_ack(upacket_recv)

                    # If this is the pkt you're looking for
                    # the packet's sequence number is the acknowledgment
                    if upacket_ack_seqnum == upacket_seq_num:
                        # increment the sequence number to go to send the next packet in the packet list
                        upacket_seq_num += 1

                        # decrement the unacknowledged packet number because
                        # we've received the correct sequence number
                        upacket_ack_count -= 1
                        print("Sender: upacket_seq_num updated: {} - unacked updated: {}\n".format(upacket_seq_num,
                                                                                                   upacket_ack_count))

                    else:
                        print("Sender: Out of order packet, expected: {} - received: {}\n".format(upacket_seq_num,
                                                                                                  upacket_ack_seqnum))
                        upacket_ack_count = 0
                        continue

                except socket.error as socerr:
                    print("Sender: Socket error: {}".format(socerr))
                    tsocket.close()
                    return

                except KeyboardInterrupt:
                    print("\nSender: Shutting down")
                    tsocket.close()
                    return

        # send final packet to let receiver know all packets have been sent
        confirm_packet = p2putils.create_packet(src_port, dest_port, -1, b"EOF")
        tsocket.sendto(confirm_packet, (ip, dest_port))

        # Close server connection and exit successfully
        end_send_time = datetime.datetime.now()
        print("Sender: File Transferred Successfully!")
        print("Sender: Time Taken - {}\n".format(end_send_time - start_send_time))
        tsocket.close()


if __name__ == "__main__":
    if len(sys.argv) == 1:
        print("Usage of file:")
        print("Use 1: python client.py <port>")

    elif len(sys.argv) == 2:
        c = Client(udp_port=int(sys.argv[-1]))
