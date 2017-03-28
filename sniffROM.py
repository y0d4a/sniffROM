import argparse, csv, sys
from matplotlib import mpl, pyplot
import matplotlib.ticker as ticker
import numpy as np

### Logic export csv file format:

#   Time [s], Packet ID, MOSI, MISO
# 0.21347662,         0, 0x05, 0xFF


FLASH_PADDED_SIZE = 20000000     # hacky flash image start size, make this better. auto detect chip size (via JEDEC ID) and adjust accordingly?
FLASH_FILL_BYTE = 0xFF
FLASH_ENDING_SIZE = FLASH_WRITES_ENDING_SIZE = FLASH_PADDED_SIZE
GRAPH_BYTES_PER_ROW = 2048

commands = {
	0x00:"No Operation",
	0x01:"Write Status Register 1",
	0x02:"Page Program",
	0x03:"Read Data",
	0x04:"Write Disable",
	0x05:"Read Status Register 1",
	0x06:"Write Enable",
	0x07:"Read Status Register 2",
	0x0B:"Fast Read Data",
	0x0C:"Fast Read Data (4-byte address)",
	0x11:"Write Status Register 3",
	0x12:"Page Program (4-byte address)",
	0x13:"Read Data (4-byte address)",
	0x14:"AutoBoot Register Read",
	0x15:"AutoBoot Register Write",    # or Read Status Register 3
	0x16:"Bank Register Read",
	0x17:"Bank Register Write",
	0x20:"Sector Erase (4K)",
	0x2B:"Read Security Register",
	0x2F:"Program Security Register",
	0x32:"Page Program (Quad I/O)",
	0x33:"Read Status Register 3",
	0x34:"Page Program (Quad I/O, 4-byte address)",
	0x35:"Enter QPI Mode", #or Read Status Register 2, or Read Configuration Register 1
	0x38:"Page Program (Quad I/O)",  # or Enter QPI Mode
	0x52:"Block Erase (32KB)",
	0x42:"Program Security Register / One Time Program (OTP) array",
	0x48:"Read Security Register",
	0x4B:"Read Unique ID / One Time Program (OTP) Array",
	0x50:"Write Enable for Volatile Status Register",
	0x5A:"Read Serial Flash Discoverable Parameters (SFDP) Register",
	0x60:"Chip Erase",
	0x66:"Enable Reset",
	0x68:"Write Protect Selection",
	0xC7:"Chip Erase",
	0xD8:"Block Erase (64KB)",
	0x90:"Read Manufacturer ID / Device ID",
	0x92:"Read Manufacturer ID / Device ID (Dual I/O)",
	0x94:"Read Manufacturer ID / Device ID (Quad I/O)",
	0x99:"Reset Device",
	0x9F:"Read JEDEC ID",
	0xAB:"Release Power-Down / Device ID",
	0xB9:"Power Down",
	0xE0:"Read Dynamic Protection Bit (DYB)",
	0xE1:"Write Dynamic Protection Bit (DYB)",
	0xE2:"Read Persistent Protection Bit (PPB)",
	0xE3:"Program Persistent Protection Bit (PPB)",
	0xE4:"Erase Persistent Protection Bit (PPB)",
	0xE7:"Password Read",
	0xE8:"Password Program",
	0xE9:"Password Unlock"}

command_stats = {
	0x00:0,
	0x01:0,
	0x02:0,
	0x03:0,
	0x04:0,
	0x05:0,
	0x06:0,
	0x07:0,
	0x0B:0,
	0x0C:0,
	0x11:0,
	0x12:0,
	0x13:0,
	0x14:0,
	0x15:0,
	0x16:0,
	0x17:0,
	0x20:0,
	0x2B:0,
	0x2F:0,
	0x32:0,
	0x33:0,
	0x34:0,
	0x35:0,
	0x38:0,
	0x52:0,
	0x42:0,
	0x48:0,
	0x4B:0,
	0x50:0,
	0x5A:0,
	0x60:0,
	0x66:0,
	0x68:0,
	0xC7:0,
	0xD8:0,
	0x90:0,
	0x92:0,
	0x94:0,
	0x99:0,
	0x9F:0,
	0xAB:0,
	0xB9:0,
	0xE0:0,
	0xE1:0,
	0xE2:0,
	0xE3:0,
	0xE4:0,
	0xE7:0,
	0xE8:0,
	0xE9:0}	

def dump(data, length, addr):
	hex = lambda line: ' '.join('{:02x}'.format(b) for b in map(ord, line))
	str = lambda line: ''.join(31 < c < 127 and chr(c) or '.' for c in map(ord, line))
	
	for i in range(0, len(data), length):
		line = data[i:i+length]
		print('  0x{:08x}   {:47}   {}'.format(addr+i, hex(line), str(line)))

def plot_func(x, pos):
	s = '0x%06x' % (int(x)*GRAPH_BYTES_PER_ROW)
	return s


def print_data(offset):
	if offset <= 4:
		bargraph = "[\033[32;40m*\033[0m-----]"
	elif offset <= 8:
		bargraph = "[\033[32;40m**\033[0m----]"
	elif offset <= 16:
		bargraph = "[\033[33;40m***\033[0m---]"
	elif offset <= 32:
		bargraph = "[\033[33;40m****\033[0m--]"
	elif offset <= 64:
		bargraph = "[\033[31;40m*****\033[0m-]"
	elif offset > 64:
		bargraph = "[\033[31;40m******\033[0m]"
		
	print ' {0} {1} bytes'.format(bargraph, offset)
	dump(str(flash_image[address:address+offset]), 16, address)
						

parser = argparse.ArgumentParser(description="sniffROM - Reconstructs flash memory contents from passively captured READ/WRITE commands in a Saleae logic analyzer exported capture file. Currently supports SPI flash chips.")
parser.add_argument("input_file", help="Saleae Logic SPI Analyzer Export File (.csv)")
parser.add_argument("--addrlen", type=int, choices=[2,3,4], nargs="?", default=3, help="Length of address in bytes (default is 3)")
parser.add_argument("--endian", choices=["msb", "lsb"], nargs="?", default="msb", help="Endianness of address bytes (default is msb first)")
parser.add_argument("--filter", choices=["r", "w", "rw"], nargs="?", default="rw", help="Parse READ, WRITE, or READ and WRITE commands (default is rw)")
parser.add_argument("-o", nargs="?", default="output.bin", help="Output binary image file (default is output.bin)")
parser.add_argument("--summary", help="Also dump statistics", action="store_true")
parser.add_argument("--graph", help="Show visual representation of flash layout", action="store_true")
parser.add_argument("-v", help="Increase verbosity (up to -vvv)", action="count")
args = parser.parse_args()

flash_image = bytearray([FLASH_FILL_BYTE] * FLASH_PADDED_SIZE)
flash_image_fromWrites = bytearray([FLASH_FILL_BYTE] * FLASH_PADDED_SIZE)
mapping_image = bytearray([0] * FLASH_PADDED_SIZE)
packet_id = -1
new_packet_id = 0
offset = 0
bytes_sniffed = 0            # this does not count re-reads of same memory addresses
bytes_sniffed_written = 0
unknown_commands = 0
jedec_id = bytearray([0x00] * 5)
device_id = 0x00
address_bytes = bytearray([0x00] * args.addrlen)

with open(args.input_file, 'rb') as infile:
	packets = csv.reader(infile)
	for packet in packets:
		if packet[1].isdigit():                # ignores the first header line
			packet_time = float(packet[0])
			new_packet_id = int(packet[1])
			mosi_data = int(packet[2], 16)
			miso_data = int(packet[3], 16)
			
			if new_packet_id > packet_id:      # IF WE GOT A NEW COMMAND INSTANCE (new Packet ID according to Saleae SPI analyzer)
				if offset > 0:                 # the new packet ID tells us the last command is finished, so dump remaining data from last command, if any
					if args.v > 1:
						print_data(offset)
						offset = 0
				
				packet_id = new_packet_id
				new_command = mosi_data
				curr_byte = 0
				curr_addr_byte = 0
				offset = 0
				dummy_byte_fastread = True
				dummy_bytes_rpddid = 0
				
				if not (new_command in commands):
					unknown_commands += 1
					command = 0x00
					if args.v > 0:
						print 'Time: {0:.8f}   Packet ID: {1:5}  Command: 0x{2:02x} - Unknown'.format(packet_time, packet_id, new_command)
				else:
					command = new_command
					command_stats[command] += 1
					if args.v > 0:
						print 'Time: {0:.8f}   Packet ID: {1:5}  Command: 0x{2:02x} - {3}'.format(packet_time, packet_id, command, commands[command])

			elif command == 0x03:              # Read command
				read_byte = miso_data          # the data in a read command comes on MISO
				addr_byte = mosi_data
				if (args.filter == 'r' or args.filter == 'rw'):
					if curr_addr_byte == args.addrlen:  # we have the whole address. read data
						if args.endian == "msb":   # TODO add if else for different address byte lengths
							address = (address_bytes[0] << 16) + (address_bytes[1] << 8) + (address_bytes[2] << 0)
						elif args.endian == "lsb":
							address = (address_bytes[2] << 16) + (address_bytes[1] << 8) + (address_bytes[0] << 0)

						if flash_image[address+offset] != FLASH_FILL_BYTE:    # hacky way to check for multiple access to this addr
							if args.v > 2:
								print ' [*] Memory address 0x{:02x} may have been accessed more than once. Perhaps it is important?'.format(address+offset)
						else:
							bytes_sniffed += 1

						flash_image[address+offset] = read_byte
						if mapping_image[address+offset] != 2:
							mapping_image[address+offset] = 1

						offset += 1
					else:   # get the address
						address_bytes[curr_addr_byte] = addr_byte
						curr_addr_byte += 1
			elif command == 0x0b:              # Fast Read cmd
				read_byte = miso_data
				addr_byte = mosi_data
				if (args.filter == 'r' or args.filter == 'rw'):
					if curr_addr_byte == args.addrlen:  # we have the whole address. read data
						if dummy_byte_fastread:                  # Fast Read command sends a dummy byte (8 clock cycles) after the address
							dummy_byte_fastread = False
						else:
							if args.endian == "msb":   # TODO add if else for different address byte lengths
								address = (address_bytes[0] << 16) + (address_bytes[1] << 8) + (address_bytes[2] << 0)
							elif args.endian == "lsb":
								address = (address_bytes[2] << 16) + (address_bytes[1] << 8) + (address_bytes[0] << 0)

							if flash_image[address+offset] != FLASH_FILL_BYTE:    # hacky way to check for multiple access to this addr
								if args.v > 2:
									print ' [*] Memory address 0x{:02x} may have been accessed more than once. Perhaps it is important?'.format(address+offset)
							else:
								bytes_sniffed += 1

							flash_image[address+offset] = read_byte
							if mapping_image[address+offset] != 2:
								mapping_image[address+offset] = 1

							offset += 1
					else:   # get the address
						address_bytes[curr_addr_byte] = addr_byte
						curr_addr_byte += 1
			elif command == 0x02:	      # page program (write) command
				write_byte = mosi_data    # the data and addr in a write command goes on MOSI
				addr_byte = mosi_data
				if (args.filter == 'w' or args.filter == 'rw'):
					if curr_addr_byte == args.addrlen:  # we have the whole address. read data
						if args.endian == "msb":
							address = (address_bytes[0] << 16) + (address_bytes[1] << 8) + (address_bytes[2] << 0)
						elif args.endian == "lsb":
							address = (address_bytes[2] << 16) + (address_bytes[1] << 8) + (address_bytes[0] << 0)

						if flash_image[address+offset] != FLASH_FILL_BYTE:    # hacky way to check for multiple access to this addr
							if args.v > 2:
								print ' [*] Memory address 0x{:02x} may have been accessed more than once. Perhaps it is important?'.format(address+offset)
						else:
							bytes_sniffed += 1

						flash_image_fromWrites[address+offset] = write_byte    # this holds write data separately
						flash_image[address+offset] = write_byte
						bytes_sniffed_written += 1
						mapping_image[address+offset] = 2
						offset += 1
					else:   # get the address
						address_bytes[curr_addr_byte] = addr_byte
						curr_addr_byte += 1	
			elif command == 0xab:           # Release Power-Down / Device ID command
				read_byte = miso_data
				if dummy_bytes_rpddid == 3:    # If this command is followed by 3 dummy bytes,
					device_id = read_byte      #  then it is a Device ID command
					if args.v > 0:
						print ' [+] Device ID: {0}'.format(hex(device_id))
				else:
					dummy_bytes_rpddid += 1
			elif command == 0x9f:           # read JEDEC ID command (1 byte MFG ID, and 1-3 byte Device ID)
				read_byte = miso_data
				if curr_byte <= 3:
					jedec_id[curr_byte] = read_byte
					curr_byte += 1
				else:
					if args.v > 0:
						print ' [+] Manufacturer ID: {0}'.format(hex(jedec_id[0]))
						print ' [+] Device ID: {0} {1}'.format(hex(jedec_id[1]), hex(jedec_id[2]))
	if offset > 0:    # this is here again to catch the very last command. otherwise we leave the for loop without having a chance to print this. kind of ugly.
		if args.v > 1:
			print_data(offset)
			offset = 0

	print 'Finished parsing input file'

# trim extra padding bytes (might lose valid data - if so edit FLASH_FILL_BYTE). this assumes last byte is a padding byte
print 'Trimming pad bytes...\n'
while ((flash_image[FLASH_ENDING_SIZE-1] == FLASH_FILL_BYTE) and (FLASH_ENDING_SIZE > 0)):
	FLASH_ENDING_SIZE -= 1
	
while ((flash_image_fromWrites[FLASH_WRITES_ENDING_SIZE-1] == FLASH_FILL_BYTE) and (FLASH_WRITES_ENDING_SIZE > 0)):
	FLASH_WRITES_ENDING_SIZE -= 1

try:
	with open(args.o, 'wb') as outfile:
		outfile.write(flash_image[0:FLASH_ENDING_SIZE])
	with open('out_write.bin', 'wb') as outfile:
		outfile.write(flash_image_fromWrites[0:FLASH_WRITES_ENDING_SIZE])
except:
	print 'Failed to write the output file'

print 'Rebuilt image: {0} bytes (saved to {1})\nCaptured data: {2} bytes ({3:.2f}%) ({4} bytes from WRITE commands)'.format(
						FLASH_ENDING_SIZE, args.o, bytes_sniffed, ((bytes_sniffed / float(FLASH_ENDING_SIZE)) * 100.0), bytes_sniffed_written)

if args.summary:
	print '\nSummary:\n'
	if jedec_id[0]:
		print 'Manufacturer ID: {0}'.format(hex(jedec_id[0]))
		print 'Device ID: {0} {1}\n'.format(hex(jedec_id[1]), hex(jedec_id[2]))
	if device_id:
		print 'Device ID: {0}\n'.format(hex(device_id))
	print '+---------+-----------+-----------------------------------------------------------+'
	print '| Command | Instances | Description                                               |'
	print '+---------+-----------+-----------------------------------------------------------+'
	for command in command_stats:
		if command_stats[command] > 0:
			print "| 0x{0:02x}    | {1:9} | {2:57} |".format(command, command_stats[command], commands[command])
	if unknown_commands > 0:
		print "| Unknown | {0:9} |                                                           |".format(unknown_commands)
	print '+---------+-----------+-----------------------------------------------------------+'


if args.graph:
	print '\nGenerating Graph...'
	mapping_bytes = []
	mapping_rows = FLASH_ENDING_SIZE / GRAPH_BYTES_PER_ROW
	mapping_remainder = FLASH_ENDING_SIZE % GRAPH_BYTES_PER_ROW
	
	for row in range(0,mapping_rows):
		mapping_bytes.append(mapping_image[row*GRAPH_BYTES_PER_ROW:(row*GRAPH_BYTES_PER_ROW)+GRAPH_BYTES_PER_ROW])	

	cmap = mpl.colors.ListedColormap(['black','blue','red'])
	bounds=[1,1,2,2]
	norm = mpl.colors.BoundaryNorm(bounds, ncolors=3)
	pyplot.imshow(mapping_bytes,interpolation='nearest',cmap=cmap,norm=norm,aspect='auto')
	pyplot.ylabel('Address')
	pyplot.xlabel('Offset')
	pyplot.grid(True,color='white')
	axes = pyplot.gca()
	axes.get_xaxis().set_major_formatter(ticker.FormatStrFormatter("0x%04x"))
	axes.get_yaxis().set_major_formatter(ticker.FuncFormatter(plot_func))
	pyplot.savefig('image.png')
	pyplot.show()
