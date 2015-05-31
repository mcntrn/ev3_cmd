#! /usr/bin/env python
#
# saved envisalinkV24
#
# This is a client side monitoring script, which uses socket, connect, send & recv.
# The server side uses: socket, bind, listen and accept.
#
# The script can be run from the command line or from a cron job.
#
# To start the command line version, in a terminal window type: python <filename>
#
# <ctrl>-c will interrupt the command line version of the script and exit gracefully
#
# While the script is running, entering: leave, sleep, disarm, panic or status will 
# send the appropriate command. disarm will also turn off the panic alarm. Both leave
# and sleep will arm the security system.
# 
# To Dos:
#	reconnect automatically if connection drops (through cron ???)
#	figure out how to communicate with web page (json, flat file, postgres/mysql)
#		Items to report on:
#			status of system: armed, disarmed
#			status of alarm: none, fire, panic, alert
#			status of zones[1-6]: open, closed
#			status of script: connected, logged-in, running
#	send text message on alert
#	replace string.split, which is deprecated with (reg edit) re.split
#	add to garage door web page
#	can large garage door sensor be added to PC1616? Yes
#	verbose should enable/disable certain repetitve output, like poll and poll ack
#	do better error checking on responses received (i.e., check length of data, and use checksum)
#	send an alert message if a door is open after 11pm 
#	basic failing system is whether or not door is locked cannot be detected
#	add try for all array lookups, and handle unexpected values
#	push constants to a config file (pswd, IP address, max_ retries, login, zones, partitions, ...) 
#	can smoke alarm be added to system?
#	add def to poll website on commands
#

import socket
import sys
import time
import datetime
import string
import re
import signal
import select
import threading;

class Envisalink:
	def __init__(self):
		self.host = '192.168.1.92'	# EnvisaLink 3's IP address
		self.port = int(4025)		# port number EnvisaLink listens on
		#
		# DON'T PUBLISH ITEMS BELOW
		#
		self.password = '6chars'		# your password - 6 characters
		self.masterCode = '0000'		# your master code - 4 digits
		self.installersCode = '5555'	# your installer's code - default is 5555
		#
		# DON'T PUBLISH ITEMS ABOVE
		#
		self.loggedin = False
		self.poll_ack = True
		self.max_poll_retries = 3
		self.poll_retries = 0
		self.max_partitions = 1
		self.max_zones = 6
		self.sleep = 0
		# Use this line when running on raspberry pi
		# self.file_log = open('/tmp/envisalink.log', 'w')
		# use this line when running from MacBook terminal window
		self.file_log = sys.stderr
		# don't use both of the above :)
		self.printMutex = threading.Lock()
		self.socketMutex = threading.Lock()
		self.modes = {'0' : 'Away', '1' : 'Stay in house', '2' : 'Zero entry away', '3' : 'Zero entry stay in house'}
		self.zones = {'001' : 'front door or door to garage', '002' : 'motion sensor', '003' : 'back door',
			'004' : 'common area windows', '005' : 'spare bedroom windows', '006' : 'master bedroom windows'
		}
		# commands needed to decode 500 ack
		self.commands = {'000' : 'poll', '001' : 'status report', '005' : 'login', 
			'008' : 'dump zone timers', '010' : 'set time and date', '020' : 'command output', 
			'030' : 'partition arm', '031' : 'stay arm', '032' : 'zero entry delay', '033' : 'arm', 
			'040' : 'disarm', '055' : 'timestamp', '056' : 'time', '057' : 'temperature', 
			'060' : 'trigger panic alarm', '070' : 'use 071 command', '071' : 'keypad command', 
			'072' : 'user code programming',
			'073' : 'user programming', '074' : 'keep alive', '200' : 'send code'
			}
		self.responses = {'500' : 'command acknowledge', '501' : 'command error', 
			'502' : 'system error', '505' : 'login', '510' : 'keypad LED state', 
			'511' : 'keypad LED flash state',
			'550' : 'time/date Broadcast', '560' : 'ring detected', '561' : 'indoor temperature',
			'562' : 'outdoor temperature', '601' : 'alarm', '602' : 'alarm clear',
			'603' : 'tamper', '604' : 'tamper clear', '605' : 'zone fault', '606' : 'zone fault clear',
			'609' : 'zone open', '610' : 'zone closed', '615' : 'zone timer dump', 
			'620' : 'duress alarm', '621' : 'fire key alarm', 
			'622' : 'fire key alarm clear', '623' : 'auxillary key alarm', '624' : 'auxillary alarm clear',
			'625' : 'panic alarm', '626' : 'panic alarm clear', '631' : 'smoke/aux alarm', 
			'632' : 'smoke/aux alarm clear', '650' : 'partition ready', '651' : 'partition not ready',
			'652' : 'partition armed', '653' : 'partition force arming enabled', '654' : 'partition alarm',
			'655' : 'partition disarmed', '656' : 'partition exit delay', '657' : 'partition entry delay',
			'658' : 'partition keypad lockout', '659' : 'partition failed to arm', 
			'660' : 'partition PGM output', '663' : 'chime enabled', '664' : 'chime disabled',
			'670' : 'partition invalid access', '671' : 'partition function not available',
			'672' : 'partition failure to arm', '673' : 'partition is busy', '674' : 'partition arming',
			'680' : 'installer\'s mode', '700' : 'partition user closing',
			'701' : 'partition armed by method', '702' : 'partition armed, but zone(s) bypassed',
			'750' : 'partition disarmed by user', '751' : 'partition disarmed by method',
			'800' : 'closet panel battery trouble', '801' : 'closet panel battery okay', 
			'802' : 'closet panel AC trouble', '803' : 'closet panel AC okay', '806' : 'system bell trouble', 
			'807' : 'system bell okay', '814' : 'closet panel cannot communicate with monitoring.',
			'816' : 'buffer nearly full', '829' : 'general system tamper', 
			'830' : 'general System Tamper Restore', '840' : 'partition trouble LED on', 
			'841' : 'partition trouble LED off', '842' : 'fire trouble alarm', 
			'843' : 'fire trouble alarm cleared', '849' : 'verbose trouble status', 
			'900' : 'code required', '912' : 'command output pressed', 
			'921' : 'master code required', '922' : 'installer\'s code required'
			}
		self.errorCodes = {'000' : 'no error', '001' : 'last command not finished', 
			'002' : 'receive buffer overflow', '003' : 'transmit buffer overflow',
			'010' : 'keybus transmit buffer overrun', '011' : 'keybus transmit time timeout',
			'012' : 'keybus transmit mode timeout',
			'013' : 'keybus transmit keystring timeout',
			'014' : 'keybus interface failure', 
			'015' : 'keybus disarming or arming with user code',
			'016' : 'keybus keypad lockout, too many disarm attempts',
			'017' : 'keybus closet panel in installer\'s mode',
			'018' : 'keybus requested partition is busy',
			'020' : 'API command syntax error', '021' : 'API partition out of bounds',
			'022' : 'API command not supported',
			'023' : 'API disarm attempted, but not armed', 
			'024' : 'API not ready to arm', '025' : 'API command invalid length',
			'026' : 'API user code not required', '027' : 'API invalid characters'
			}
	
	def connect(self):
		try:
			self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
			self.socket.connect((self.host, self.port))
			self.socket.settimeout(None)
			self.socket.setblocking(0)
			self.printNormal('system: connect ' + str(self.host) + ' on port ' + str(self.port))
			self.status['system'] = 'connected'
		except socket.error, (value,message):
			self.printFatal(message)
		
	def login(self):
		time.sleep(1)
		self.sendCommand(005, 'login', self.password)

	def sendCommand(self, command, msg, data_bytes = []):
		# send one message at a time
		self.socketMutex.acquire()
		try:
			cmd_bytes = str(command).zfill(3)
			cmd = []
			checksum = 0
			for byte in cmd_bytes:
				cmd.append(byte)
				checksum += ord(byte)
			for byte in data_bytes:
				cmd.append(byte)
				checksum += ord(byte)

			checksum = checksum % 256
			cmd.extend([hex(nibble)[-1].upper() for nibble in [ checksum / 16, checksum % 16]])
			cmd.extend((chr(0x0D), chr(0x0A)))

			self.printNormal("send [" + ''.join(cmd[:len(cmd)-4]) + "]: " + msg)

			try:
				self.socket.send(''.join(cmd))
			except socket.error, err:
				e.printFatal('socket error '+ str(err[0]) + ' in sendCommand ' )

		finally:
			self.socketMutex.release()

	def receiveResponse(self):
		try:
			msg = ''
			while True: 
				rsp = self.socket.recv(4096)
				if len(rsp) == 0: 
					# try to re-establish connection
					self.printNormal('Envisalink closed the connection. Try to reconnect')
					return 'c'
					# self.printFatal('Envisalink closed the connection')
				# remove return and line feed
				words = string.split(rsp, '\r\n')
				if words == ['']:
					break

				msg = 'm'
				# remove checksum and decode word
				# might want to use checksum before processing response
				for i in range(0,len(words)):
					word = ''.join(words[i][:len(words[i])-2])
					if word != '':
						words[i] = word
						self.decodeResponse(word)
			return msg
			
		except socket.error, (value,message):
			# non-blocking socket correctly returns an error of temporarily unavailable
			# self.printNormal('system: ' + message)
			return ''
		return ''

	def decodeResponse(self, word):
		cmd = word[:3]
		msg = 'received [' + word + ']: '

		if cmd == '':
			return
		elif cmd == '500':
			data = word[3:6]
			if data != '':
				if data == '000':
					self.loggedin = True
					self.poll_ack = True
					self.sleep = 0
					self.status['system'] = 'logged in'
				self.printNormal(msg + "ack " + self.commands[data])
			else:
				self.printNormal(msg + "no ack command")
		elif cmd == '501':
			self.printNormal(msg + 'command error, bad checksum')
		elif cmd == '502':
			data = word[3:6]
			self.printNormal(msg + 'system error = ' + self.errorCodes[data])
		elif cmd == '505':
			if word[3:4] == '0':
				self.printFatal(msg + "password is incorrect")
			elif word[3:4] == '1':
				self.printNormal(msg + "login successful")
				self.status['system'] = 'logged in'
				self.loggedin = True
			elif word[3:4] == '2':
				self.printFatal(msg + "login timed out. password not sent within 10 seconds of connection.")
			elif word[3:4] == '3':
				self.printNormal(msg + "socket setup. request password")
				# this is where login should go, but it is much less reliable
				# and causes problems
				# self.login()
		elif cmd == '510':
			self.status['system'] = 'disarmed'
			msg += 'lit keypad LEDs = '
			b = int(word[3:5],16)
			
			# Bit 0 - Ready LED lit
			if b & 0x01 != 0:
				msg += 'ready '
			# Bit 1 - Armed LED lit
			if b & 0x02 != 0:
				msg += 'armed '
				self.status['system'] = 'armed'
			# Bit 2 - Memory LED lit
			if b & 0x04 != 0:
				msg += 'memory '
			# Bit 3 - Bypass LED lit
			if b & 0x08 != 0:
				msg += 'bypass '
			# Bit 4 - Trouble LED lit
			if b & 0x10 != 0:
				msg += 'trouble '
			# Bit 5 - Program LED lit
			if b & 0x20 != 0:
				msg += 'program '
			# Bit 6 - Fire LED lit
			if b & 0x40 != 0:
				msg += 'fire '
			# Bit 7 - Backlight LED lit
			if b & 0x80 != 0:
				msg += 'backlight '
			
			self.printNormal(msg)
		elif cmd == '511':
			msg += 'flashing keypad LEDs = '
			b = int(word[3:5],16)
			
			# Bit 0 - Ready LED lit
			if b & 0x01 != 0:
				msg += 'ready '
			# Bit 1 - Armed LED lit
			if b & 0x02 != 0:
				msg += 'armed '
			# Bit 2 - Memory LED lit
			if b & 0x04 != 0:
				msg += 'memory '
			# Bit 3 - Bypass LED lit
			if b & 0x08 != 0:
				msg += 'bypass '
			# Bit 4 - Trouble LED lit
			if b & 0x10 != 0:
				msg += 'trouble '
			# Bit 5 - Program LED lit
			if b & 0x20 != 0:
				msg += 'program '
			# Bit 6 - Fire LED lit
			if b & 0x40 != 0:
				msg += 'fire '
			# Bit 7 - Backlight LED lit
			if b & 0x80 != 0:
				msg += 'backlight '
			
			self.printNormal(msg)
		elif cmd == '550':
			self.printNormal(msg + 'time and date ' + word[3:5] + ":" + word[5:7] + " " + word[7:9] + "/" + word[9:11] + "/20" + word[11:13])
		elif cmd == '560':
			self.printNormal(msg + 'ring detected')
		elif cmd == '561':
			self.printNormal(msg + 'indoor temperature = ' + word[3:7])
		elif cmd == '562':
			self.printNormal(msg + 'outdoor temperature = ' + word[3:7])
		elif cmd == '601':
			zone = word[4:7]
			partition = word[3:4]
			if int(zone) <= self.max_zones:
				if int(partition) <= self.max_partitions:
					self.printNormal(msg + 'alarm. partition = ' + partition + ' zone = ' + self.zones[zone])
			# sent alert on alarm
		elif cmd == '602':
			zone = word[4:7]
			partition = word[3:4]
			if int(zone) <= self.max_zones:
				if int(partition) <= self.max_partitions:
					self.printNormal(msg + 'alarm cleared. partition = ' + partition + ' zone = ' + self.zones[zone])
		elif cmd == '603':
			zone = word[4:7]
			partition = word[3:4]
			if int(zone) <= self.max_zones:
				if int(partition) <= self.max_partitions:
					self.printNormal(msg + 'tamper. partition = ' + partition + ' zone = ' + self.zones[zone])
		elif cmd == '604':
			zone = word[4:7]
			partition = word[3:4]
			if int(zone) <= self.max_zones:
				if int(partition) <= self.max_partitions:
					self.printNormal(msg + 'tamper cleared. partition = ' + partition + ' zone = ' + self.zones[zone])
		elif cmd == '605':
			zone = word[3:6]
			if int(zone) <= self.max_zones:
				self.printNormal(msg + 'zone ' + self.zones[zone] + ' fault')
		elif cmd == '606':
			zone = word[3:6]
			if int(zone) <= self.max_zones:
				self.printNormal(msg + 'zone ' + self.zones[zone] + ' fault cleared')
		elif cmd == '609':
			zone = word[3:6]
			if int(zone) <= self.max_zones:
				self.printNormal(msg + 'zone ' + self.zones[zone] + ' open')
		elif cmd == '610':
			zone = word[3:6]
			if int(zone) <= self.max_zones:
				self.printNormal(msg + 'zone ' + self.zones[zone] + ' closed')
		elif cmd == '615':
			# don't care about all the zone timers
			self.printNormal('received [615]: zone timer dump')
		elif cmd == '620':
			self.printNormal(msg + 'duress alarm')
		elif cmd == '621':
			self.printNormal(msg + 'fire key alarm detected')
		elif cmd == '622':
			self.printNormal(msg + 'fire key alarm restored')
		elif cmd == '623':
			self.printNormal(msg + 'auxillary key alarm detected')
		elif cmd == '624':
			self.printNormal(msg + 'auxillary key alarm restored')
		elif cmd == '625':
			self.printNormal(msg + 'panic key detected')
		elif cmd == '626':
			self.printNormal(msg + 'panic key restored')
		elif cmd == '631':
			self.printNormal(msg + 'smoke/aux alarm detected')
		elif cmd == '632':
			self.printNormal(msg + 'smoke/aux alarm restored')
		elif cmd == '650':
			partition = word[3:4]
			if int(partition) <= self.max_partitions:
				self.printNormal(msg + 'partition ' + partition + ' ready')
		elif cmd == '651':
			partition = word[3:4]
			if int(partition) <= self.max_partitions:
				self.printNormal(msg + 'partition ' + partition + ' not ready')
		elif cmd == '652':
			partition = word[3:4]
			if int(partition) <= self.max_partitions:
				self.printNormal(msg + 'partition ' + partition + ' armed, mode = ' + self.modes[word[4:5]])
		elif cmd == '653':
			partition = word[3:4]
			if int(partition) <= self.max_partitions:
				self.printNormal(msg + 'partition ' + partition + ' forcing alarm enabled')
		elif cmd == '654':
			partition = word[3:4]
			if int(partition) <= self.max_partitions:
				self.printNormal(msg + 'partition ' + partition + ' in alarm')
		elif cmd == '655':
			partition = word[3:4]
			if int(partition) <= self.max_partitions:
				self.printNormal(msg + 'partition ' + partition + ' disarmed')
		elif cmd == '656':
			partition = word[3:4]
			if int(partition) <= self.max_partitions:
				self.printNormal(msg + 'partition ' + partition + ' exit delay')
		elif cmd == '657':
			partition = word[3:4]
			if int(partition) <= self.max_partitions:
				self.printNormal(msg + 'partition ' + partition + ' entry delay')
		elif cmd == '658':
			partition = word[3:4]
			if int(partition) <= self.max_partitions:
				self.printNormal(msg + 'partition ' + partition + ' keypad lockout')
		elif cmd == '659':
			partition = word[3:4]
			if int(partition) <= self.max_partitions:
				self.printNormal(msg + 'partition ' + partition + ' failed to arm')
		elif cmd == '660':
			partition = word[3:4]
			if int(partition) <= self.max_partitions:
				self.printNormal(msg + 'partition ' + partition + ' PGM output')
		elif cmd == '663':
			partition = word[3:4]
			if int(partition) <= self.max_partitions:
				self.printNormal(msg + 'partition ' + partition + ' chime enabled')
		elif cmd == '664':
			partition = word[3:4]
			if int(partition) <= self.max_partitions:
				self.printNormal(msg + 'partition ' + partition + ' chime disabled')
		elif cmd == '670':
			partition = word[3:4]
			if int(partition) <= self.max_partitions:
				self.printNormal(msg + 'partition ' + partition + ' invalid access code')
		elif cmd == '671':
			partition = word[3:4]
			if int(partition) <= self.max_partitions:
				self.printNormal(msg + 'partition ' + partition + ' function not available')
		elif cmd == '672':
			partition = word[3:4]
			if int(partition) <= self.max_partitions:
				self.printNormal(msg + 'partition ' + partition + ' failure to arm')
		elif cmd == '673':
			partition = word[3:4]
			if int(partition) <= self.max_partitions:
				self.printNormal(msg + 'partition ' + partition + ' is busy')
		elif cmd == '674':
			partition = word[3:4]
			if int(partition) <= self.max_partitions:
				self.printNormal(msg + 'partition ' + partition + ' is arming')
		elif cmd == '680':
			self.printNormal(msg + 'system in installer\'s mode')
		elif cmd == '700':
			partition = word[3:4]
			if int(partition) <= self.max_partitions:
				self.printNormal(msg + 'partition = ' + partition + 'armed by user')
		elif cmd == '701':
			partition = word[3:4]
			if int(partition) <= self.max_partitions:
				self.printNormal(msg + 'partition ' + partition + ' armed by method')
		elif cmd == '702':
			partition = word[3:4]
			if int(partition) <= self.max_partitions:
				self.printNormal(msg + 'partition ' + partition + ' armed but zone(s) bypassed')
		elif cmd == '750':
			partition = word[3:4]
			if int(partition) <= self.max_partitions:
				self.printNormal(msg + 'partition ' + partition + ' disarmed by user')
		elif cmd == '751':
			partition = word[3:4]
			if int(partition) <= self.max_partitions:
				self.printNormal(msg + 'partition ' + partition + ' partition disarmed by method')
		elif cmd == '800':
			self.printNormal(msg + 'closet panel battery trouble')
		elif cmd == '801':
			self.printNormal(msg + 'closet panel battery restore')
		elif cmd == '802':
			self.printNormal(msg + 'closet panel AC trouble')
		elif cmd == '803':
			self.printNormal(msg + 'closet panel AC retored')
		elif cmd == '806':
			self.printNormal(msg + 'bell trouble')
		elif cmd == '807':
			self.printNormal(msg + 'bell restored')
		elif cmd == '814':
			self.printNormal(msg + 'closet panel failed to communicate with monitoring')
		elif cmd == '816':
			self.printNormal(msg + 'buffer near full')
		elif cmd == '829':
			self.printNormal(msg + 'general system tamper')
		elif cmd == '830':
			self.printNormal(msg + 'general system tamper cleared')
		elif cmd == '840':
			partition = word[3:4]
			if int(partition) <= self.max_partitions:
				self.printNormal(msg + 'partition ' + partition + ' trouble LED on')
		elif cmd == '841':
			partition = word[3:4]
			if int(partition) <= self.max_partitions:
				self.printNormal(msg + 'partition ' + partition + ' trouble LED off')
		elif cmd == '842':
			self.printNormal(msg + 'fire trouble alarm')
		elif cmd == '843':
			self.printNormal(msg + 'fire trouble alarm cleared')
		elif cmd == '849':
			msg += 'verbose trouble status = '
			b = int(word[3:5],16)

			# Bit 0 - Service required
			if b & 0x01 != 0:
				msg += 'service required | '
			# Bit 1 - AC power lost
			if b & 0x02 != 0:
				msg += 'AC power lost | '
			# Bit 2 - telephone line fault
			if b & 0x04 != 0:
				msg += 'telephone line fault (ignore) | '
			# Bit 3 - failure to communicate
			if b & 0x08 != 0:
				msg += 'failure to communicate | '
			# Bit 4 - sensor/zone fault
			if b & 0x10 != 0:
				msg += 'sensor/zone fault | '
			# Bit 5 - sensor/zone tamper
			if b & 0x20 != 0:
				msg += 'sensor zone tamper | '
			# Bit 6 - low battery
			if b & 0x40 != 0:
				msg += 'low battery '
			
			self.printNormal(msg)
		elif cmd == '900':
			self.printNormal(msg + 'code required')
			# the master code should be a variable and in a config file
			self.sendCommand('200', 'code send', self.masterCode)
		elif cmd == '912':
			# don't care about data 
			self.printNormal(msg + 'command output pressed')
		elif cmd == '921':
			self.printNormal(msg + 'master code required')
		elif cmd == '922':
			self.printNormal(msg + 'installer\'s code required')
		else:
			if len(msg) > 20:
				self.printNormal("received[too long]: unhandled response")
			else:
				self.printNormal(msg + "unhandled response")
		return

	def timeStamp(self):
		t = time.time()
		s = datetime.datetime.fromtimestamp(t).strftime('%Y/%m/%d %H:%M:%S - ')
		return s

	def printNormal(self, msg):
		self.printMutex.acquire()
		try:
			print >> self.file_log, self.timeStamp() + msg
		finally:
			self.printMutex.release()
		

	def printFatal(self, msg):
		self.printMutex.acquire()
		try:
			try:
				print >> self.file_log, self.timeStamp() + "fatal: " + msg
				self.socket.shutdown(SHUT_RDWR)
				time.sleep(1)
				self.socket.close()
			except socket.error, (value,message):
				print >> self.file_log, self.timeStamp() + "system: " + message
		finally:
			self.printMutex.release()
			self.exitData()
			sys.exit()

	def printData(self):
		self.file_data = open('/tmp/envisalink.data', 'w')
		print >> self.file_data, self.status
		print >> self.file_data, self.status_zones
		self.file_data.close()

	def resetData(self):
		self.status = {'system' : 'unknown', 'alarm' : 'unknown', 'script' : 'unknown'}
		self.status_zones = {'001' : 'unknown', '002' : 'unknown', '003' : 'unknown', '004' : 'unknown', '005' : 'unknown', '006' : 'unknown'} 

	def exitData(self):
		self.resetData()
		self.printData()

	def heardEnter(self):
		i,o,e = select.select([sys.stdin],[],[],0.0001)
		for s in i:
			if s == sys.stdin:
				k = sys.stdin.readline()
				k = k[:len(k)-1]
				if k == 'sleep':
					self.sendCommand('031', 'keyboard: sleep (arm stay)', '1')
				elif k == 'leave':
					self.sendCommand('030', 'keyboard: leave (arm leave)', '1')
				elif k == 'disarm':
					self.sendCommand('040', 'keyboard: disarm', '1' + self.masterCode)
				elif k == 'panic':
					self.sendCommand('060', 'keyboard: panic', '1')
				elif k == 'status':
					self.sendCommand('001', 'keyboard: status')
				else:
					self.printNormal('keyboard: unrecognized command = ' + k)
					self.printNormal('recognized commands: sleep, leave, disarm, panic, status')
		return

	def getStatus(self):
		self.sendCommand(001, 'get status')
		return True

	def poll(self):
		if self.poll_ack == True:
			self.poll_ack = False
			self.poll_retries = 0
			self.sendCommand(0, 'poll')
		else:
			if self.poll_retries == self.max_poll_retries:
				# try to reconnect ?	
				self.printFatal('connection closed, no response to poll')
			else:
				self.sendCommand(0, 'poll')
				self.poll_retries += 1
				self.printNormal('system: poll retry = ' + str(self.poll_retries))
				
		# every 60s * N minutes send a poll
		self.p = threading.Timer(60*10, e.poll)
		self.p.daemon = True
		self.p.start()
		return 

	def openFileDescriptors(self):
		import os
		numfd = os.dup(0)	# 0=stdin, can be any valid file descriptor
		os.close(numfd)		# close the just-duplicated descr
		return numfd 


if __name__ == '__main__':
		try:
			e = Envisalink()
			e.printNormal('system: start envisalink script')
			e.resetData()
			e.connect()
			e.login()

			# get status of security system
			e.getStatus()

			e.poll()
		
			# monitor loop
			max_login_wait = 3
			login_wait = 0
			e.sleep = 0
			while(True):
				e.heardEnter()
				rsp = e.receiveResponse()
				if rsp == 'c':
					e.socket.close()
					e.resetData()
					time.sleep(10)
					e.loggedin = False
					login_wait = 0
					e.sleep = 0
					e.connect()
					e.login()
				elif rsp == '':
					e.sleep += 1
					if e.sleep == 10:
						if e.loggedin == False:
							if login_wait == max_login_wait:
								e.printFatal('failed to login or logged out')
							else:
								login_wait += 1
								e.printNormal('system: login wait = ' + str(login_wait))
						e.sleep = 0
					else:
						time.sleep(1)
				else:
					# does it ever get here ?
					e.printNormal('system: rsp = ' + rsp)

		except KeyboardInterrupt:
			e.printFatal('closing script through ctrl-c')
		except socket.error, err:
			e.printFatal('socket error ' + str(err[0]))
