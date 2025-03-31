import logging
import time
import PID
import datetime
import socket
import subprocess

# Existing logging setup
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

# set info log depth
extended_info = 1  # Set to 1 for extended info, 0 for simple info

# Add a FileHandler to write logs to a .txt file -- turned off for now
#file_handler = logging.FileHandler('/mnt/Icculus/FanController/logs/logfile.txt')  # Log file path
#file_handler.setLevel(logging.INFO)  # Set level for file handler
##formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
#file_handler.setFormatter(formatter)

# Add the file handler to the root logger
#logging.getLogger().addHandler(file_handler)

# don't care about debug/info level logging from either of these packages
loggers_to_set_to_warning = ['paramiko.transport', 'invoke']
for l in loggers_to_set_to_warning:
    logging.getLogger(l).setLevel(logging.WARNING)

user = "root"
password = r"password"
host = None  # this is set via hostname detection below
DESIRED_CPU_TEMP = 42
CPU_HYSTERESIS = 8 # range is desired +/- hysteresis
CPU_UPPER = DESIRED_CPU_TEMP + CPU_HYSTERESIS
DESIRED_MB_TEMP = 42
MB_HYSTERESIS = 8 # range is desired +/- hysteresis
MIN_CASE_FAN_PCT = 10
CASE_FAN_STEP_PCT = MIN_CASE_FAN_PCT + 5
MIN_CPU_FAN_PCT = 10
CPU_FAN_STEP_PCT = MIN_CPU_FAN_PCT + 5
NOCTUA_FAN_PCT = 50 # initial condition
counter = 0

# setting this since it is needed below -- won't matter once loop starts
cpu_fan_value = MIN_CPU_FAN_PCT
case_fan_value = MIN_CASE_FAN_PCT

# set fan max speeds based on absolute temperature (manage noise)
def get_max_speed(temp):
    fan_speeds = {
        (-40, 45): 20, 
        (45, CPU_UPPER): 30, 
        (CPU_UPPER, 55): 40, 
        (55, 65): 55,
        (65, 70): 80,
        (70, 80): 90,
        (80, float('inf')): 100,
    }
    
    for (low, high), speed in fan_speeds.items():
        if low <= temp < high:
            return speed
    return 100  # Default if temperature is out of range

#drives_to_monitor = ['da0', 'da1', 'da2', 'da3', 'nvme0', 'nvme1', 'nvme2'] ## not used currently

# command to set fans via ipmitool
# ipmitool raw 0x3a 0x01 0x04 0x04  0x04  0x04  0x04  0x04  0x04 0x04
                         #cpu #fan1 #fan2 #fan3 #fan4 #fan5 ??   ??
                         #b   #noc #noc #noc #b   #b   ??
                         #cpu #1   #2   #3   #4   #5   ??

BASE_RAW_IPMI = 'raw 0x3a 0x01'
INITIAL_STATE = ['0x0'] * 8 # all 25% -- default to auto at startup
FAN_CURRENT_STATE = INITIAL_STATE


# set variables for later
current_sensor_readings = {}
cpu_temp_sensor = "CPU1 Temp"
cpu_fan_sensor = "CPU_FAN1"
case_fans = ["SYSTEM_FAN1", "SYSTEM_FAN2", "SYSTEM_FAN3", 'SYSTEM_FAN4', 'SYSTEM_FAN5']
mb_temp_sensor = "MB Temp"

# Hysteresis flags
cpu_fan_active = False
mb_fan_active = False
cpu_step_active = False


# Flag to track if we've changed from True to False
# start with all true since fans are set artifically right now
cpu_fan_was_active = True
mb_fan_was_active = True
cpu_step_was_active = True

def limiter(input_value, min_value, max_value):
    return max(min_value, min(input_value, max_value))

def adjust_cpu_fan_setpoint(value):
    FAN_CURRENT_STATE[0] = str(int(value))
    
def adjust_case_fan_setpoint(value):
    for i in range(len(FAN_CURRENT_STATE) - 1):
        if i + 1 in [1, 2, 4, 6, 7]:
            FAN_CURRENT_STATE[i + 1] = str(int(NOCTUA_FAN_PCT))
        else:
            FAN_CURRENT_STATE[i + 1] = str(int(value))
            
def set_fans_via_ipmi_bak():
        result = subprocess.run(['ipmitool', 'raw', '0x3a', '0x01',
                                 '0x' + FAN_CURRENT_STATE[0], 
                                 '0x' + FAN_CURRENT_STATE[1],
                                 '0x' + FAN_CURRENT_STATE[2],
                                 '0x' + FAN_CURRENT_STATE[3],
                                 '0x' + FAN_CURRENT_STATE[4],
                                 '0x' + FAN_CURRENT_STATE[5],
                                 '0x' + FAN_CURRENT_STATE[6],
                                 '0x' + FAN_CURRENT_STATE[7]], stdout=subprocess.PIPE)
def set_fans_via_ipmi():
        result = subprocess.run(['ipmitool', 'raw', '0x3a', '0x01',
                                 FAN_CURRENT_STATE[0], 
                                 FAN_CURRENT_STATE[1],
                                 FAN_CURRENT_STATE[2],
                                 FAN_CURRENT_STATE[3],
                                 FAN_CURRENT_STATE[4],
                                 FAN_CURRENT_STATE[5],
                                 FAN_CURRENT_STATE[6],
                                 FAN_CURRENT_STATE[7]], stdout=subprocess.PIPE)
                                 
def populate_sensor_readings(sensor, value):
    current_sensor_readings[sensor] = value

def query_ipmitool():
    result = subprocess.run(['ipmitool', 'sensor'], stdout=subprocess.PIPE)
    result = result.stdout.decode('utf-8')
    for line in result.split('\n'):
        if line:
            row_data = line.split('|')
            current_sensor_readings[row_data[0].strip()] = row_data[1].strip()

def wait_until_top_of_second():
    time.sleep(1 - (time.time() % 1))
   
   
def run_logger():
     # simple info logging
    if extended_info == 0:
        logging.info(f'CPU: {cpu_temp:5.2f} MB: {mb_temp:5.2f} CPU PID: {cpu_pid.output:5.2f} MB PID: {mb_pid.output:5.2f}')
    
    if extended_info == 1: 
        fan_percentages = [round(int(val), 1) for val in FAN_CURRENT_STATE]
        logging.info('\n'
             "---------------------------------\n"
             f'CPU TEMP: {cpu_temp:5.2f} CPU PID: {cpu_pid.output:5.2f} CPU FAN ACTIVE: {cpu_fan_active} WAS CPU FAN ACTIVE?: {cpu_fan_was_active}\n'
             f' MB TEMP: {mb_temp:5.2f}  MB PID: {mb_pid.output:5.2f}   MB FAN ACTIVE: {mb_fan_active} WAS MB FAN ACTIVE?: {mb_fan_was_active} \n'
             f'STEP FAN ACTIVE: {cpu_step_active} WAS STEP FAN ACTIVE?: {cpu_step_was_active}\n'
             f'MAX SPEED: {max_speed:3.0f}%\n'
             "---------------------------------\n"
             "---------------------------------\n"
             "|  Fan Name       | Percentage  |\n"
             "---------------------------------\n"
             f"| CPU1 Fan        | {fan_percentages[0]:>10.1f}% |\n"
             f"| SYSTEM_FAN1     | {fan_percentages[1]:>10.1f}% |\n"
             f"| SYSTEM_FAN2     | {fan_percentages[2]:>10.1f}% |\n"
             f"| SYSTEM_FAN3     | {fan_percentages[3]:>10.1f}% |\n"
             f"| SYSTEM_FAN4     | {fan_percentages[4]:>10.1f}% |\n"
             f"| SYSTEM_FAN5     | {fan_percentages[5]:>10.1f}% |\n"
             f"| EMPTY           | {fan_percentages[6]:>10.1f}% |\n"
             f"| EMPTY           | {fan_percentages[7]:>10.1f}% |\n"
             "---------------------------------\n")

# PID loop for CPU and MB temperatures
cpu_pid = PID.PID(4.0, 2.5, 0.1)
cpu_pid.SetPoint = DESIRED_CPU_TEMP

mb_pid = PID.PID(2.5, 1.5, 0.1)
mb_pid.SetPoint = DESIRED_MB_TEMP

# set initial state
set_fans_via_ipmi()


# set last_execution to now minus one minute to force first execution
wait_until_top_of_second()
last_execution = datetime.datetime.now() - datetime.timedelta(minutes=1)



while True:
    query_ipmitool()
    #print(current_sensor_readings)
    cpu_temp = float(current_sensor_readings[cpu_temp_sensor])
    mb_temp = float(current_sensor_readings[mb_temp_sensor])
    max_speed = get_max_speed(cpu_temp)
    

   
    # Hysteresis logic for CPU fan
    if cpu_temp >= DESIRED_CPU_TEMP + CPU_HYSTERESIS:
        cpu_fan_active = True
    elif cpu_temp <= DESIRED_CPU_TEMP:
        cpu_fan_active = False
        
    # Hysteresis logic for CPU fan non-active step
    if cpu_temp >= DESIRED_CPU_TEMP + CPU_HYSTERESIS/4:
        cpu_step_active = True
    elif cpu_temp <= DESIRED_CPU_TEMP:
        cpu_step_active = False
    
    if mb_temp >= DESIRED_MB_TEMP + MB_HYSTERESIS:
        mb_fan_active = True
    elif mb_temp <= DESIRED_MB_TEMP:
        mb_fan_active = False
        
    # NOTHING WRONG
    # if neither are active and no state change, pause and check again in 15 seconds (16)
    if (not cpu_fan_active and not cpu_fan_was_active) and (not cpu_step_active and not cpu_step_was_active):
        print('16')
        wait_until_top_of_second()
        run_logger()
        time.sleep(15) 
        counter = 0 
        continue
        
    # if fans are inactive but step is active, sleep and check again in 15 seconds (13)
    if (not cpu_fan_active and not cpu_fan_was_active) and (cpu_step_active and cpu_step_was_active):
        print('13')
        wait_until_top_of_second()
        run_logger()
        time.sleep(15)
        counter = 0
        continue
    
    # (Transition -- Fans on to Fans off) (3, 7, 9, 10, 11, 12, 15)
    # If either fan goes from active to inactive or step fan goes from active to inactive -- set all fans to minimums
    if (not cpu_fan_active and cpu_fan_was_active) or (not cpu_step_active and cpu_step_was_active):
        print('3, 7, 9, 10, 11, 12, 15')
        NOCTUA_FAN_PCT = 50
        cpu_fan_value = MIN_CPU_FAN_PCT
        adjust_cpu_fan_setpoint(cpu_fan_value) 

        case_fan_value = MIN_CASE_FAN_PCT
        adjust_case_fan_setpoint(case_fan_value)
        
        set_fans_via_ipmi()
        
        cpu_fan_was_active = False
        cpu_step_was_active = False
        wait_until_top_of_second()
        run_logger()
        continue
        
    # (Transition -- Fans off to Step Fan) (14)
    # If step is active, but step wasn't taken yet -- take the step
    if not cpu_fan_active and (cpu_step_active and not cpu_step_was_active):
        print('14')
        NOCTUA_FAN_PCT = 100
        cpu_fan_value = CASE_FAN_STEP_PCT
        adjust_cpu_fan_setpoint(cpu_fan_value)
        case_fan_value = MIN_CASE_FAN_PCT
        adjust_case_fan_setpoint(case_fan_value)
        set_fans_via_ipmi()
        cpu_step_was_active = True
        wait_until_top_of_second()
        run_logger()
        continue 
    
    # if none of conditions above hold -- then continue with loop and set according to PIDS & max speed dictionary (1,2,5,6) -- 4/8 are not possible so ignore but if they happened you'd end here.
    # update PIDs
    cpu_pid.update(cpu_temp)
    mb_pid.update(mb_temp)
    max_speed = get_max_speed(cpu_temp)
    
    # increment counter and if loops 20 times - add 5 to max speed to try and get over hump
    counter += 1 
    if counter >= 20: max_speed = min(max_speed + 5, 100)

    # set noctua fans to 100 (quiet)
    NOCTUA_FAN_PCT = 100
    
    # set target speed and then ramp to this speed
    target_speed = limiter(-1 * cpu_pid.output, MIN_CPU_FAN_PCT, max_speed)
    cpu_step_size = max((target_speed - cpu_fan_value)/5,1)
    if cpu_fan_value < target_speed:
        cpu_fan_value += cpu_step_size
    else:
        cpu_fan_value = target_speed
    case_step_size = max((target_speed - case_fan_value)/5,1)
    if case_fan_value < target_speed:
        case_fan_value += case_step_size
    else:
        case_fan_value = target_speed
    
    adjust_cpu_fan_setpoint(cpu_fan_value) 
    adjust_case_fan_setpoint(case_fan_value)
    set_fans_via_ipmi()
    
    cpu_fan_was_active = True
    mb_fan_was_active = True
    cpu_step_was_active = True
    
    # loop infinitely
    last_execution = datetime.datetime.now()
    wait_until_top_of_second()
    run_logger()
    continue