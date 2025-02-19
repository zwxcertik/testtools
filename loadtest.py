import subprocess
import threading
import time
import logging
from datetime import datetime
import json
import argparse
import re
from datetime import datetime
from typing import Dict, Tuple, NamedTuple, Optional, List
from tabulate import tabulate
import numpy as np
import random
from tqdm import tqdm
import configparser


config = configparser.ConfigParser()
config.read("./config.txt")

IPLIST = [ip.strip() for ip in config.get('Network', 'ip_list').split(',')]
NODEPORT = config.getint('Network', 'node_port')
CONTRACT_ID = config.get('Contract', 'contract_id')
class BenchmarkMetrics(NamedTuple):
    duration:int
    account_num:int
    test_start_time: datetime    
    test_end_time: datetime     
    timestamp: datetime         
    start_tick: int
    end_tick: int
    total_unique_txs: int
    total_ticks: int
    total_txhashes: int
    total_transfers: int
    avg_transfers_per_tick: float
    tps: float
    tick_distribution: Dict[int, int]
    transfers_distribution: Dict[int, int]
    avg_tick_time: float

def setup_logging(test_index: Optional[int] = None):
    
    logging.getLogger().handlers = []
    
    if test_index is not None:
        log_filename = f"qubic_benchmark_integrate_{test_index}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
    else:
        log_filename = f"qubic_benchmark_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
    
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s",
        handlers=[
            logging.FileHandler(log_filename),
            logging.StreamHandler()
        ]
    )
    return log_filename


def read_seeds(filename):
    with open(filename, 'r') as file:
        seeds = [line.strip() for line in file.readlines()]
    return seeds

def get_id(seed):
    ip = random.choice(IPLIST)
    command = f"./qubic-cli -nodeip {ip} -nodeport {NODEPORT} -seed {seed} -showkeys"
    result = subprocess.run(command, shell=True, capture_output=True, text=True)
    output_lines = result.stdout.splitlines()
    if len(output_lines) >= 4:
        return output_lines[3].split(": ")[1]
    return None
def verify_tx_hash(tick: int, tx_hash: str, max_retries: int = 10, retry_delay: float = 1.0) -> bool:
    def check_wait_tick(output: str) -> Optional[Tuple[int, int]]:
        match = re.search(r"Requested tick (\d+), current tick (\d+)", output)
        if match:
            return int(match.group(1)), int(match.group(2))
        return None
    
    for attempt in range(max_retries):
        try:
            ip = random.choice(IPLIST)
            command = f"./qubic-cli -nodeip {ip} -nodeport {NODEPORT} -checktxontick {tick} {tx_hash}"
            result = subprocess.run(command, shell=True, capture_output=True, text=True)
            output = result.stdout.strip()
            
            
            # Check for connection error
            if "No connection" in output:
                
                time.sleep(retry_delay)
                continue
            wait_info = check_wait_tick(output)
            if wait_info:
                time.sleep(retry_delay)
                continue
            
            if "Can NOT find tx" in output:
                
                return False

            return True
            
        except Exception as e:
            if attempt < max_retries - 1:
                time.sleep(retry_delay)
            else:
                return False
    
    return False
def verifytickhashes(file: str) -> None:
    try:

        with open(file, 'r') as f:
            tick_data_json = json.load(f)
        
        for tick, tx_hashes in tick_data_json.items():
            for tx_hash in tx_hashes:
                if verify_tx_hash(tick, tx_hash):
                    print(f"Verified: Tick: {tick}, TxHash: {tx_hash}")
                else:
                    print(f"Failed to verify: Tick: {tick}, TxHash: {tx_hash}")
    
    except Exception as e:
        print(f"Error reading or processing file {file}: {e}")

def get_balance(id):
    output_lines = []
    balance_info = {}
    while(len(output_lines) <=1 ):
        ip = random.choice(IPLIST)
        command = f"./qubic-cli -nodeip {ip} -nodeport {NODEPORT} -getbalance {id}"
        result = subprocess.run(command, shell=True, capture_output=True, text=True)
        output_lines = result.stdout.splitlines()
        

    for line in output_lines:
        if ":" in line:
            key, value = line.split(": ", 1)  
            balance_info[key.strip()] = value.strip()
    return balance_info
def get_current_tick():
    output_lines = []
    while(len(output_lines) <=1 ):
        ip = random.choice(IPLIST)
        command = f"./qubic-cli -nodeip {ip} -nodeport {NODEPORT} -getcurrenttick"
        result = subprocess.run(command, shell=True, capture_output=True, text=True)
        output_lines = result.stdout.splitlines()
        if len(output_lines) >= 4:
            key, value = output_lines[0].split(": ", 1) 
            return value 

def send_benchmark(seed: str, account_num: int, max_retries: int = 10, retry_delay: float = 0.1) -> Optional[Dict[str, str]]:
    
    
    for attempt in range(max_retries):
        ip = random.choice(IPLIST)
        command = f"./qubic-cli -nodeip {ip} -nodeport {NODEPORT} -scheduletick 5 -seed {seed} -qutilsendtomanybenchmark {account_num} 1"
        try:
            result = subprocess.run(command, shell=True, capture_output=True, text=True)
            output = result.stdout

            if "No connection" in output:
                time.sleep(retry_delay)
                continue

            receipt = {}
            if "~~~~~RECEIPT~~~~~" in output:
                receipt_lines = output.split("~~~~~RECEIPT~~~~~")[1].split("~~~~~END-RECEIPT~~~~~")[0].strip().splitlines()
                for line in receipt_lines:
                    if ":" in line:
                        key, value = line.split(": ")
                        receipt[key] = value
                return receipt

            time.sleep(retry_delay)

        except Exception as e:
            print(f"Error on attempt {attempt + 1}/{max_retries}: {str(e)}")
            if attempt < max_retries - 1:
                time.sleep(retry_delay)
            else:
                print("All retry attempts failed")
                raise
    
    return None

def run_benchmarks(seeds, duration, account_num):
    stop_event = threading.Event()
    threads = []
    tick_data_all = {}
    hash_set = set()
    lock = threading.Lock()
    
    while True:
        current_tick = get_current_tick()
        if current_tick and current_tick.isdigit():
            current_tick = int(current_tick)
            break
        time.sleep(0.1)
    
    processed_seeds = {}
    transfers_per_tick = {}  
    last_balance = get_balance(CONTRACT_ID)  
    last_processed_tick = current_tick  
    
    def benchmark_task(seed):
        nonlocal current_tick, last_balance, last_processed_tick
        local_hash_set = set()
        tick_data = {}

        while not stop_event.is_set():
            try:
                new_tick_str = get_current_tick()
                if not new_tick_str or not new_tick_str.isdigit():
                    time.sleep(0.1)
                    continue
                
                new_tick = int(new_tick_str)
                
                if new_tick > last_processed_tick:  
                    with lock:
                        if new_tick > last_processed_tick:  
                            new_balance = get_balance(CONTRACT_ID)
                            old_out = int(last_balance.get("Outgoing Amount", 0))
                            new_out = int(new_balance.get("Outgoing Amount", 0))
                            transfer_count = new_out - old_out
                            
                            transfers_per_tick[last_processed_tick] = transfer_count
                            logging.info(f"Transfers in Tick {last_processed_tick}: {transfer_count}")

                            last_balance = new_balance
                            processed_seeds.clear()
                            current_tick = new_tick
                            last_processed_tick = new_tick
                        
                if current_tick not in processed_seeds.get(seed, set()):
                    r = send_benchmark(seed, account_num)
                    if r and r.get("Tick") and len(r.get("Tick")) > 5:  
                        tick = r["Tick"]
                        if not tick.isdigit():  
                            continue
                            
                        with lock:
                            tx_hash = r["TxHash"]
                            if seed not in processed_seeds:
                                processed_seeds[seed] = set()
                            processed_seeds[seed].add(tick)
                            if tick not in tick_data:
                                tick_data[tick] = set()
                            tick_data[tick].add(tx_hash)
                            local_hash_set.add(tx_hash)
                            
                            if tick not in tick_data_all:
                                tick_data_all[tick] = set()
                            tick_data_all[tick].update(tick_data[tick])
                            hash_set.update(local_hash_set)
            except Exception as e:
                logging.error(f"Error in benchmark task: {e}")
                time.sleep(0.1)
                continue
                
            time.sleep(0.1)

    for seed in seeds:
        thread = threading.Thread(target=benchmark_task, args=(seed,))
        threads.append(thread)
        thread.start()

    time.sleep(duration * 60)

    stop_event.set()
    for thread in threads:
        thread.join()

    if last_processed_tick not in transfers_per_tick:
        new_balance = get_balance(CONTRACT_ID)
        old_out = int(last_balance.get("Outgoing Amount", 0))
        new_out = int(new_balance.get("Outgoing Amount", 0))
        transfer_count = new_out - old_out
        transfers_per_tick[last_processed_tick] = transfer_count
        logging.info(f"Transfers in Tick {last_processed_tick}: {transfer_count}")

    return {tick: list(tx_hashes) for tick, tx_hashes in tick_data_all.items()}, hash_set, transfers_per_tick
def dump_tick_hashes(tick_data_all):
    output_file = f"qubic_benchmark_tick_data{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    try:
        with open(output_file, 'w') as f:
            json.dump(tick_data_all, f, indent=4)
        print(f"Tick data has been written to {output_file}")
    except Exception as e:
        print(f"Error writing to file: {e}")
    return output_file
def conclude_data(tick_data_all, duration, transfers_per_tick, total_transfers, total_ticks, verify=False):
    tick_hashes = dump_tick_hashes(tick_data_all)
    total_tx_hashes = 0

    for tick, tx_hashes in tick_data_all.items():
        tx_hashes_count = len(tx_hashes)
        total_tx_hashes += tx_hashes_count
        logging.info(f"Tick: {tick}, TxHashes: {tx_hashes_count}")

    avg_transfers_per_tick = total_transfers / len(transfers_per_tick) if transfers_per_tick else 0
    avg_tick_time = (duration * 60) / total_ticks if total_ticks > 0 else 0  

    logging.info(f"Total Ticks: {total_ticks}")
    logging.info(f"Total TxHashes: {total_tx_hashes}")
    logging.info(f"Total Transfers: {total_transfers}")
    logging.info(f"Average Transfers per Tick: {avg_transfers_per_tick:.2f}")
    logging.info(f"Average Tick Time: {avg_tick_time:.2f} seconds")  
    logging.info(f"Number Of Transfers Per Second (TPS): {total_transfers / (duration * 60)}")

    if verify:
        verifytickhashes(tick_hashes)

def loadtest(duration: int, account_num: int, verify: bool = False, test_index: Optional[int] = None) -> str:
    log_filename = setup_logging(test_index)
    seeds = read_seeds("seeds.txt")
    start_tick = get_current_tick()

    logging.info(f"Test Parameters:")
    logging.info(f"  Duration: {duration} minutes")
    logging.info(f"  Account Number: {account_num}")
    old_balance = get_balance(CONTRACT_ID)
    logging.info(f"Test Starting At Tick: {start_tick}\n")
    tick_data_all, unique_tx_hashes, transfers_per_tick = run_benchmarks(seeds, duration, account_num)
    end_tick = get_current_tick()
    logging.info(f"Test Ending At Tick: {end_tick}\n")
    new_balance = get_balance(CONTRACT_ID)
    old_out = int(old_balance.get("Outgoing Amount", 0))
    new_out = int(new_balance.get("Outgoing Amount", 0))
    logging.info(f"Total unique TxHashes: {len(unique_tx_hashes)}")
    conclude_data(tick_data_all, duration, transfers_per_tick, new_out-old_out, end_tick-start_tick+1, verify)
    
    return log_filename

def run_integration_test(num_tests: int, duration: int, interval: int, account_num: int):
    print(f"\nStarting integration test with following parameters:")
    print(f"Number of tests: {num_tests}")
    print(f"Test duration: {duration} minutes")
    print(f"Interval: {interval} minutes")
    print(f"Accounts per tx: {account_num}")
    print("-" * 50)
    
    log_files = []
    total_time = num_tests * (duration + interval) - interval
    
    try:
        with tqdm(total=total_time, desc="Overall Progress", unit="min") as pbar:
            for i in range(num_tests):
                print(f"\nTest {i+1}/{num_tests}")
                
                # Run test with current index
                log_file = loadtest(
                    duration=duration,
                    account_num=account_num,
                    verify=False,
                    test_index=i+1
                )
                log_files.append(log_file)
                
                # Update progress bar for test duration
                pbar.update(duration)
                
                # Wait for interval if this is not the last test
                if i < num_tests - 1:
                    print(f"\nWaiting {interval} minutes before next test...")
                    for _ in range(interval):
                        time.sleep(60)
                        pbar.update(1)
        
        # Compare all test results and generate report
        print("\nAll tests completed. Comparing results...")
        print(f"Log files generated: {', '.join(log_files)}")
        
        comparison_data = compare_logs(log_files)
        
        
        report_file = generate_test_report(
            test_type="integration",
            log_files=log_files,
            comparison_data=comparison_data
        )
        
        # Display report
        read_test_report(report_file)
        
    except KeyboardInterrupt:
        print("\nTest interrupted by user.")
        if log_files:
            print("\nGenerating report for completed tests...")
            comparison_data = compare_logs(log_files)
            report_file = generate_test_report(
                test_type="integration",
                log_files=log_files,
                comparison_data=comparison_data
            )
            read_test_report(report_file)
            
    except Exception as e:
        print(f"\nError during integration test: {e}")
        if log_files:
            print("\nGenerating report for completed tests...")
            comparison_data = compare_logs(log_files)
            report_file = generate_test_report(
                test_type="integration",
                log_files=log_files,
                comparison_data=comparison_data
            )
            read_test_report(report_file)

def extract_timestamp_from_filename(filename: str) -> datetime:
    pattern = r'qubic_benchmark(?:_(?:integrate|random)_\d+)?_(\d{8}_\d{6})'
    match = re.search(pattern, filename)
    if match:
        timestamp_str = match.group(1)
        return datetime.strptime(timestamp_str, '%Y%m%d_%H%M%S')
    raise ValueError(f"Invalid filename format: {filename}")
def parse_log_file(file_path: str) -> BenchmarkMetrics:

    try:
        with open(file_path, 'r') as f:
            content = f.read()
        
        # Extract timestamp from filename
        timestamp = extract_timestamp_from_filename(file_path)
        
        # Extract test parameters
        duration_match = re.search(r'Duration: (\d+) minutes', content)
        if not duration_match:
            raise ValueError(f"Could not find duration in {file_path}")
        duration = int(duration_match.group(1))
        
        account_num_match = re.search(r'Account Number: (\d+)', content)
        if not account_num_match:
            raise ValueError(f"Could not find account number in {file_path}")
        account_num = int(account_num_match.group(1))
        
        # Extract test start time
        start_time_match = re.search(r'(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d{3}) - INFO - Test Starting At Tick:', content)
        if not start_time_match:
            raise ValueError(f"Could not find start time in {file_path}")
        test_start_time = datetime.strptime(start_time_match.group(1), '%Y-%m-%d %H:%M:%S,%f')
        
        # Extract test end time
        end_time_match = re.search(r'(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d{3}) - INFO - Test Ending At Tick:', content)
        if not end_time_match:
            raise ValueError(f"Could not find end time in {file_path}")
        test_end_time = datetime.strptime(end_time_match.group(1), '%Y-%m-%d %H:%M:%S,%f')
        
        # Extract ticks
        start_tick_match = re.search(r'Test Starting At Tick: (\d+)', content)
        if not start_tick_match:
            raise ValueError(f"Could not find start tick in {file_path}")
        start_tick = int(start_tick_match.group(1))
        
        end_tick_match = re.search(r'Test Ending At Tick: (\d+)', content)
        if not end_tick_match:
            raise ValueError(f"Could not find end tick in {file_path}")
        end_tick = int(end_tick_match.group(1))
        
        # Extract metrics
        total_unique_txs_match = re.search(r'Total unique TxHashes: (\d+)', content)
        if not total_unique_txs_match:
            raise ValueError(f"Could not find total unique txhashes in {file_path}")
        total_unique_txs = int(total_unique_txs_match.group(1))
        
        total_ticks_match = re.search(r'Total Ticks: (\d+)', content)
        if not total_ticks_match:
            raise ValueError(f"Could not find total ticks in {file_path}")
        total_ticks = int(total_ticks_match.group(1))
        
        total_txhashes_match = re.search(r'Total TxHashes: (\d+)', content)
        if not total_txhashes_match:
            raise ValueError(f"Could not find total txhashes in {file_path}")
        total_txhashes = int(total_txhashes_match.group(1))
        
        # Extract tick distribution
        tick_pattern = r'INFO - Tick: (\d+), TxHashes: (\d+)'
        tick_matches = re.finditer(tick_pattern, content)
        tick_distribution = {}
        for match in tick_matches:
            tick = int(match.group(1))
            txhashes = int(match.group(2))
            tick_distribution[tick] = txhashes
        
        if not tick_distribution:
            raise ValueError(f"Could not find any tick distributions in {file_path}")
        
        # Extract transfers
        total_transfers_match = re.search(r'Total Transfers: (\d+)', content)
        if not total_transfers_match:
            raise ValueError(f"Could not find total transfers in {file_path}")
        total_transfers = int(total_transfers_match.group(1))
        
        avg_transfers_match = re.search(r'Average Transfers per Tick: ([\d.]+)', content)
        if not avg_transfers_match:
            raise ValueError(f"Could not find average transfers per tick in {file_path}")
        avg_transfers_per_tick = float(avg_transfers_match.group(1))
        
        tps_match = re.search(r'Number Of Transfers Per Second \(TPS\): ([\d.]+)', content)
        if not tps_match:
            raise ValueError(f"Could not find TPS in {file_path}")
        tps = float(tps_match.group(1))

        # Extract transfers distribution
        transfers_pattern = r'INFO - Transfers in Tick (\d+): (\d+)'
        transfers_matches = re.finditer(transfers_pattern, content)
        transfers_distribution = {}
        for match in transfers_matches:
            tick = int(match.group(1))
            transfers = int(match.group(2))
            transfers_distribution[tick] = transfers
        avg_tick_time_match = re.search(r'Average Tick Time: ([\d.]+) seconds', content) 
        if not avg_tick_time_match:
            raise ValueError(f"Could not find average tick time in {file_path}")
        avg_tick_time = float(avg_tick_time_match.group(1)) 
        return BenchmarkMetrics(
            duration=duration,
            account_num=account_num,
            test_start_time=test_start_time,
            test_end_time=test_end_time,
            timestamp=timestamp,
            start_tick=start_tick,
            end_tick=end_tick,
            total_unique_txs=total_unique_txs,
            total_ticks=total_ticks,
            total_txhashes=total_txhashes,
            total_transfers=total_transfers,
            avg_transfers_per_tick=avg_transfers_per_tick,
            tps=tps,
            tick_distribution=tick_distribution,
            transfers_distribution=transfers_distribution,
            avg_tick_time=avg_tick_time
        )
    except Exception as e:
        print(f"Error parsing {file_path}: {str(e)}")
        raise


def compare_logs(log_files: List[str]) -> Dict:
    # Parse all log files
    metrics = []
    for file in log_files:
        try:
            metric = parse_log_file(file)
            metrics.append((file, metric))
        except Exception as e:
            print(f"Error parsing file {file}: {e}")
            continue
    
    # Check if we have any valid metrics
    if not metrics:
        raise ValueError("No valid log files were parsed")
    
    # Sort metrics by TPS in descending order
    metrics.sort(key=lambda x: x[1].tps, reverse=True)
    
    # Calculate averages and maximums
    total_transfers_values = [metric.total_transfers for _, metric in metrics]
    tps_values = [metric.tps for _, metric in metrics]
    
    total_transfers_avg = np.mean(total_transfers_values)
    total_transfers_max = np.max(total_transfers_values)
    tps_avg = np.mean(tps_values)
    tps_max = np.max(tps_values)
    
    # Prepare comparison data
    comparison_data = []
    for file, metric in metrics:
        tick_values = list(metric.transfers_distribution.values())
        tick_min = np.min(tick_values) if tick_values else 0
        tick_max = np.max(tick_values) if tick_values else 0
        tick_var = np.var(tick_values) if tick_values else 0
        
        total_transfers_diff_avg = metric.total_transfers - total_transfers_avg
        total_transfers_diff_max = metric.total_transfers - total_transfers_max
        tps_diff_avg = metric.tps - tps_avg
        tps_diff_max = metric.tps - tps_max
        
        test_duration = (metric.test_end_time - metric.test_start_time).total_seconds()
        tick_range = metric.end_tick - metric.start_tick  
        avg_tick_time = test_duration / tick_range if tick_range > 0 else 0

        
        row = {
            'Filename': file,
            'Test Start Time': metric.test_start_time.strftime('%Y-%m-%d %H:%M:%S'),
            'Test End Time': metric.test_end_time.strftime('%Y-%m-%d %H:%M:%S'),
            'Test Duration': f"{metric.duration} minutes",
            'Account Num': metric.account_num,
            'Start Tick': metric.start_tick,
            'End Tick': metric.end_tick,
            'Tick Range': tick_range,
            'Average Tick Time': f"{metric.avg_tick_time:.2f}s",
            'Total Unique TxHashes': metric.total_unique_txs,
            'Total Ticks': metric.total_ticks,
            'Total Transfers': metric.total_transfers,
            'Avg Transfers/Tick': f"{metric.avg_transfers_per_tick:.2f}",
            'TPS': f"{metric.tps:.2f}",
            'Transfer/Tick Min': f"{tick_min:.2f}",
            'Transfer/Tick Max': f"{tick_max:.2f}",
            'Transfer/Tick Variance': f"{tick_var:.2f}",
            'Total Transfers Diff from Avg': f"{total_transfers_diff_avg:+.2f}",
            'Total Transfers Diff from Max': f"{total_transfers_diff_max:+.2f}",
            'TPS Diff from Avg': f"{tps_diff_avg:+.2f}",
            'TPS Diff from Max': f"{tps_diff_max:+.2f}"
        }
        comparison_data.append(row)

    result = {
        'headers': list(comparison_data[0].keys()),
        'data': comparison_data,
        'summary': {
            'total_transfers_avg': f"{total_transfers_avg:.2f}",
            'total_transfers_max': f"{total_transfers_max:.2f}",
            'tps_avg': f"{tps_avg:.2f}",
            'tps_max': f"{tps_max:.2f}",
            'test_count': len(metrics)
        }
    }
    

    print("\nBenchmark Comparison (Sorted by TPS):")
    
    basic_info = []
    basic_headers = ["Test", "Start Time", "End Time", "Duration", "Account Num"]
    for i, row in enumerate(comparison_data, 1):
        basic_info.append([
            f"Test {i}",
            row['Test Start Time'],
            row['Test End Time'],
            row['Test Duration'],
            row['Account Num']
        ])
    print("\nTest Information:")
    print(tabulate(basic_info, headers=basic_headers, tablefmt='grid'))

    tick_info = []
    tick_headers = ["Test", "Start Tick", "End Tick", "Tick Range", "Total Ticks", "Avg Tick Time"]
    for i, row in enumerate(comparison_data, 1):
        tick_info.append([
            f"Test {i}",
            row['Start Tick'],
            row['End Tick'],
            row['Tick Range'],
            row['Total Ticks'],
            row['Average Tick Time']
        ])
    print("\nTick Information:")
    print(tabulate(tick_info, headers=tick_headers, tablefmt='grid'))

    performance_info = []
    performance_headers = ["Test", "Total Transfers", "Avg Transfers/Tick", "TPS", 
                        "Transfer/Tick Min", "Transfer/Tick Max", "Transfer/Tick Variance"]
    for i, row in enumerate(comparison_data, 1):
        performance_info.append([
            f"Test {i}",
            row['Total Transfers'],
            row['Avg Transfers/Tick'],
            row['TPS'],
            row['Transfer/Tick Min'],
            row['Transfer/Tick Max'],
            row['Transfer/Tick Variance']
        ])
    print("\nPerformance Metrics:")
    print(tabulate(performance_info, headers=performance_headers, tablefmt='grid'))

    return result

def generate_test_report(test_type: str, log_files: List[str], comparison_data: dict) -> str:
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    report_file = f"qubic_benchmark_{test_type}_report_{timestamp}.json"
    
    report = {
        'test_type': test_type,
        'timestamp': timestamp,
        'log_files': log_files,
        'comparison_data': comparison_data,
        'summary': {
            'total_tests': comparison_data['summary']['test_count'],
            'avg_tps': comparison_data['summary']['tps_avg'],
            'max_tps': comparison_data['summary']['tps_max'],
            'avg_transfers': comparison_data['summary']['total_transfers_avg'],
            'max_transfers': comparison_data['summary']['total_transfers_max']
        }
    }
    
    with open(report_file, 'w') as f:
        json.dump(report, f, indent=4)
    
    print(f"\nTest report saved to: {report_file}")
    return report_file

def read_test_report(report_file: str) -> None:
    try:
        with open(report_file, 'r') as f:
            report = json.load(f)
        
        print("\n" + "="*50)
        print(f"Test Report ({report['test_type'].upper()})")
        print("="*50)
        
        print(f"\nTimestamp: {report['timestamp']}")
        print(f"Number of tests: {report['summary']['total_tests']}")
        
        basic_info = []
        basic_headers = ["Test", "Start Time", "End Time", "Duration", "Account Num"]
        for i, row in enumerate(report['comparison_data']['data'], 1):
            basic_info.append([
                f"Test {i}",
                row['Test Start Time'],
                row['Test End Time'],
                row['Test Duration'],
                row['Account Num']
            ])
        print("\nTest Information:")
        print(tabulate(basic_info, headers=basic_headers, tablefmt='grid'))

        tick_info = []
        tick_headers = ["Test", "Start Tick", "End Tick", "Tick Range", "Total Ticks", "Avg Tick Time"]
        for i, row in enumerate(report['comparison_data']['data'], 1):
            tick_info.append([
                f"Test {i}",
                row['Start Tick'],
                row['End Tick'],
                row['Tick Range'],
                row['Total Ticks'],
                row['Average Tick Time']
            ])
        print("\nTick Information:")
        print(tabulate(tick_info, headers=tick_headers, tablefmt='grid'))

        performance_info = []
        performance_headers = ["Test", "Total Transfers", "Avg Transfers/Tick", "TPS", 
                            "Transfer/Tick Min", "Transfer/Tick Max", "Transfer/Tick Variance"]
        for i, row in enumerate(report['comparison_data']['data'], 1):
            performance_info.append([
                f"Test {i}",
                row['Total Transfers'],
                row['Avg Transfers/Tick'],
                row['TPS'],
                row['Transfer/Tick Min'],
                row['Transfer/Tick Max'],
                row['Transfer/Tick Variance']
            ])
        print("\nPerformance Metrics:")
        print(tabulate(performance_info, headers=performance_headers, tablefmt='grid'))

        diff_info = []
        diff_headers = ["Test", "TPS", "TPS Diff (Avg)", "TPS Diff (Max)",
                      "Transfers", "Transfers Diff (Avg)", "Transfers Diff (Max)"]
        for i, row in enumerate(report['comparison_data']['data'], 1):
            diff_info.append([
                f"Test {i}",
                row['TPS'],
                row['TPS Diff from Avg'],
                row['TPS Diff from Max'],
                row['Total Transfers'],
                row['Total Transfers Diff from Avg'],
                row['Total Transfers Diff from Max']
            ])
        print("\nComparative Analysis:")
        print(tabulate(diff_info, headers=diff_headers, tablefmt='grid'))

        print("\nSummary Statistics:")
        summary_data = [
            ["Average TPS", f"{report['summary']['avg_tps']}"],
            ["Maximum TPS", f"{report['summary']['max_tps']}"],
            ["Average Total Transfers", f"{report['summary']['avg_transfers']}"],
            ["Maximum Total Transfers", f"{report['summary']['max_transfers']}"]
        ]
        print(tabulate(summary_data, headers=['Metric', 'Value'], tablefmt='grid'))
        
        # Log Files
        print("\nDetailed logs stored in:")
        for log_file in report['log_files']:
            print(f"  - {log_file}")
            
    except Exception as e:
        print(f"Error reading report file: {e}")
        raise
def run_random_test(num_tests: int):
    ACCOUNT_OPTIONS = [int(i * 500000) for i in range(1, 34)]
    print(f"\nStarting random test with {num_tests} iterations")
    print("-" * 50)
    
    log_files = []
    test_params = []
    
    try:
        # Create progress bar for overall progress
        with tqdm(total=num_tests, desc="Tests Completed", unit="test") as pbar:
            for i in range(num_tests):
                # Generate random parameters
                duration = random.randint(2, 8)
                account_num = random.choice(ACCOUNT_OPTIONS)
                
                print(f"\nTest {i+1}/{num_tests}")
                print(f"Parameters: duration={duration}min, accounts={account_num}")
                
                # Store parameters for report
                test_params.append({
                    "test_number": i+1,
                    "duration": duration,
                    "account_num": account_num
                })
                
                # Run test
                log_file = loadtest(
                    duration=duration,
                    account_num=account_num,
                    verify=False,
                    test_index=i+1
                )
                log_files.append(log_file)
                
                # Update progress
                pbar.update(1)
                
                # Add small delay between tests
                if i < num_tests - 1:
                    time.sleep(60)  # 5 seconds between tests
        
        # Compare all test results
        print("\nAll tests completed. Comparing results...")
        
        # Capture comparison data
        comparison_data = compare_logs(log_files)
        
        # Generate report
        report_file = generate_test_report(
            test_type="random",
            log_files=log_files,
            comparison_data=comparison_data
        )
        
        # Display report
        read_test_report(report_file)
        
    except KeyboardInterrupt:
        print("\nTest interrupted by user.")
        if log_files:
            print("\nGenerating report for completed tests...")
            comparison_data = compare_logs(log_files)
            report_file = generate_test_report(
                test_type="random",
                log_files=log_files,
                comparison_data=comparison_data
            )
            read_test_report(report_file)
    except Exception as e:
        print(f"\nError during random test: {e}")
        if log_files:
            print("\nGenerating report for completed tests...")
            comparison_data = compare_logs(log_files)
            report_file = generate_test_report(
                test_type="random",
                log_files=log_files,
                comparison_data=comparison_data
            )
            read_test_report(report_file)
def main():
    parser = argparse.ArgumentParser(description='Qubic benchmark test and log analysis')
    
    subparsers = parser.add_subparsers(dest='command', help='available commands')
    
    # Existing commands
    test_parser = subparsers.add_parser('test', help='run benchmark test')
    test_parser.add_argument('-d', '--duration', type=int, required=True,
                          help='test duration in minutes')
    test_parser.add_argument('-n', '--num-accounts', type=int, required=True,
                          help='number of accounts to transfer in single tx')
    test_parser.add_argument('-v', '--verify', action='store_true',
                          help='verify transaction hashes during test')
    
    verify_parser = subparsers.add_parser('verify', help='verify transaction hashes from file')
    verify_parser.add_argument('-f', '--file', type=str, required=True,
                            help='JSON file to verify')
    
    compare_parser = subparsers.add_parser('compare', help='compare benchmark log files')
    compare_parser.add_argument('log_files', nargs='+',
                             help='log files to compare (minimum 2 files)')
    
    integrate_parser = subparsers.add_parser('integrate', 
                                           help='run multiple tests and compare results')
    integrate_parser.add_argument('-n', '--num-tests', type=int, required=True,
                               help='number of test iterations')
    integrate_parser.add_argument('-d', '--duration', type=int, required=True,
                               help='duration of each test in minutes')
    integrate_parser.add_argument('-i', '--interval', type=int, required=True,
                               help='interval between tests in minutes')
    integrate_parser.add_argument('-a', '--num-accounts', type=int, required=True,
                               help='number of accounts to transfer in single tx')
    
    # New random test command
    random_parser = subparsers.add_parser('random', 
                                        help='run random tests with varying parameters')
    random_parser.add_argument('-n', '--num-tests', type=int, required=True,
                            help='number of random test iterations')
    
    # New report reading command
    report_parser = subparsers.add_parser('report',
                                        help='read and display a test report')
    report_parser.add_argument('-f', '--file', type=str, required=True,
                            help='report file to read')
    
    args = parser.parse_args()
    
    if args.command == 'test':
        loadtest(args.duration, args.num_accounts, args.verify)
    elif args.command == 'verify':
        verifytickhashes(args.file)
    elif args.command == 'compare':
        if len(args.log_files) < 2:
            parser.error("At least two log files are required for comparison")
        compare_logs(args.log_files)
    elif args.command == 'integrate':
        run_integration_test(args.num_tests, args.duration, args.interval, args.num_accounts)
    elif args.command == 'random':
        run_random_test(args.num_tests)
    elif args.command == 'report':
        read_test_report(args.file)
    else:
        parser.print_help()
if __name__ == "__main__":
    main()
