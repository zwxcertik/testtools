import subprocess
import threading
import time
import logging
from datetime import datetime
import json
import argparse
import re
from datetime import datetime
from typing import Dict, Tuple, NamedTuple, Optional
import pandas as pd
from tabulate import tabulate
import random
CONTRACT_ID = "EAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAVWRF"
IPLIST = ["91.210.226.50", "91.210.226.47", "91.210.226.29"]
NODEPORT = 31841
def setup_logging():
    log_filename = f"qubic_benchmark_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s",
        handlers=[
            logging.FileHandler(log_filename),  
            logging.StreamHandler()  
        ]
    )

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
    ip = random.choice(IPLIST)
    command = f"./qubic-cli -nodeip {ip} -nodeport {NODEPORT} -checktxontick {tick} {tx_hash}"
    
    def check_wait_tick(output: str) -> Optional[Tuple[int, int]]:
        match = re.search(r"Requested tick (\d+), current tick (\d+)", output)
        if match:
            return int(match.group(1)), int(match.group(2))
        return None
    
    for attempt in range(max_retries):
        try:
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
    ip = random.choice(IPLIST)
    command = f"./qubic-cli -nodeip {ip} -nodeport {NODEPORT} -getbalance {id}"
    result = subprocess.run(command, shell=True, capture_output=True, text=True)
    output_lines = result.stdout.splitlines()
    balance_info = {}

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
    
    ip = random.choice(IPLIST)
    command = f"./qubic-cli -nodeip {ip} -nodeport {NODEPORT} -seed {seed} -qutilsendtomanybenchmark {account_num} 1"
    
    for attempt in range(max_retries):
        try:
            result = subprocess.run(command, shell=True, capture_output=True, text=True)
            output = result.stdout

            # Check for connection error
            if "No connection" in output:
                #print(f"Connection error on attempt {attempt + 1}/{max_retries}, retrying...")
                time.sleep(retry_delay)
                continue

            # Process receipt if found
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

    def benchmark_task(seed):
        local_hash_set = set()
        tick_data = {}  
        while not stop_event.is_set():
            r = send_benchmark(seed, account_num)  
            if r:
                tick = r["Tick"]
                tx_hash = r["TxHash"]
                if tick not in tick_data:
                    tick_data[tick] = set()  
                tick_data[tick].add(tx_hash)  
                local_hash_set.add(tx_hash)
        with lock: 
            for tick, tx_hashes in tick_data.items():
                if tick not in tick_data_all:
                    tick_data_all[tick] = set()  
                tick_data_all[tick].update(tx_hashes)  
            hash_set.update(local_hash_set)
    for seed in seeds:
        thread = threading.Thread(target=benchmark_task, args=(seed,))
        threads.append(thread)
        thread.start()

    time.sleep(duration * 60)

    stop_event.set()
    for thread in threads:
        thread.join()

    return {tick: list(tx_hashes) for tick, tx_hashes in tick_data_all.items()}, hash_set
def dump_tick_hashes(tick_data_all):
    output_file = f"qubic_benchmark_tick_data{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    try:
        with open(output_file, 'w') as f:
            json.dump(tick_data_all, f, indent=4)
        print(f"Tick data has been written to {output_file}")
    except Exception as e:
        print(f"Error writing to file: {e}")
    return output_file
def conclude_data(tick_data_all, duration, old_balance_info, start_tick, end_tick, verify=False):
    tick_hashes = dump_tick_hashes(tick_data_all)
    
    total_ticks = len(tick_data_all)
    total_tx_hashes = 0
    total_time = duration * 60  

    max_tx_hashes = 0
    min_tx_hashes = float('inf') 

    for tick, tx_hashes in tick_data_all.items():
        tx_hashes_count = len(tx_hashes)
        total_tx_hashes += tx_hashes_count

        if tx_hashes_count > max_tx_hashes:
            max_tx_hashes = tx_hashes_count
        if tx_hashes_count < min_tx_hashes:
            min_tx_hashes = tx_hashes_count

        logging.info(f"Tick: {tick}, TxHashes: {tx_hashes_count}")

    average_tx_per_tick = total_tx_hashes / total_ticks if total_ticks > 0 else 0
    average_tick_time = total_time / total_ticks if total_ticks > 0 else 0

    logging.info(f"Total Ticks: {total_ticks}")
    logging.info(f"Total TxHashes: {total_tx_hashes}")
    logging.info(f"Average TxHashes per Tick: {average_tx_per_tick}")
    logging.info(f"Average Time per Tick: {average_tick_time:.2f} seconds")
    logging.info(f"Max TxHashes per Tick: {max_tx_hashes}")
    logging.info(f"Min TxHashes per Tick: {min_tx_hashes}")

    new_balance_info = get_balance(CONTRACT_ID)
    old_out = int(old_balance_info.get("Number Of Outgoing Transfers", 0))
    new_out = int(new_balance_info.get("Number Of Outgoing Transfers", 0))
    total_out = new_out - old_out

    logging.info(f"Number Of Total Transfers In Tick {end_tick} - {start_tick} : {total_out}")
    logging.info(f"Number Of Transfers Per Second (TPS): {total_out / (duration * 60)}")

    if(verify):
        verifytickhashes(tick_hashes)

def loadtest(duration, account_num, verify=False):
    setup_logging()  
    seeds = read_seeds("seeds.txt")
    
    old_balance_info = get_balance(CONTRACT_ID)
    start_tick = get_current_tick()
    logging.info(f"Test Starting At Tick: {start_tick}\n")

    tick_data_all, unique_tx_hashes = run_benchmarks(seeds, duration, account_num)
    
    end_tick = get_current_tick()
    logging.info(f"Test Ending At Tick: {end_tick}\n")
    logging.info(f"Total unique TxHashes: {len(unique_tx_hashes)}")
    conclude_data(tick_data_all, duration, old_balance_info, start_tick, end_tick, verify)

class BenchmarkMetrics(NamedTuple):
    test_start_time: datetime    
    test_end_time: datetime     
    timestamp: datetime         
    start_tick: int
    end_tick: int
    total_unique_txs: int
    total_ticks: int
    total_txhashes: int
    avg_txhashes_per_tick: float
    avg_time_per_tick: float
    tps: float
    max_txhashes: int
    min_txhashes: int
    tick_distribution: Dict[int, int]
def extract_timestamp_from_filename(filename: str) -> datetime:
    """Extract timestamp from benchmark log filename"""
    pattern = r'qubic_benchmark_(\d{8}_\d{6})'
    match = re.search(pattern, filename)
    if match:
        timestamp_str = match.group(1)
        return datetime.strptime(timestamp_str, '%Y%m%d_%H%M%S')
    raise ValueError(f"Invalid filename format: {filename}")

def parse_log_file(file_path: str) -> BenchmarkMetrics:
    with open(file_path, 'r') as f:
        content = f.read()
    
    with open(file_path, 'r') as f:
        content = f.read()
    
    # Extract timestamp from filename
    timestamp = extract_timestamp_from_filename(file_path)
    
    # Extract actual test times
    start_time_match = re.search(r'(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d{3}) - INFO - Test Starting At Tick:', content)
    end_time_match = re.search(r'(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d{3}) - INFO - Test Ending At Tick:', content)
    
    if not start_time_match or not end_time_match:
        raise ValueError(f"Could not find test time information in {file_path}")
    
    test_start_time = datetime.strptime(start_time_match.group(1), '%Y-%m-%d %H:%M:%S,%f')
    test_end_time = datetime.strptime(end_time_match.group(1), '%Y-%m-%d %H:%M:%S,%f')

    # Updated regex patterns to match exact log format
    start_tick_match = re.search(r'Test Starting At Tick: (\d+)', content)
    if not start_tick_match:
        raise ValueError(f"Could not find start tick in {file_path}")
    start_tick = int(start_tick_match.group(1))

    end_tick_match = re.search(r'Test Ending At Tick: (\d+)', content)
    if not end_tick_match:
        raise ValueError(f"Could not find end tick in {file_path}")
    end_tick = int(end_tick_match.group(1))

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

    avg_txhashes_match = re.search(r'Average TxHashes per Tick: ([\d.]+)', content)
    if not avg_txhashes_match:
        raise ValueError(f"Could not find average txhashes per tick in {file_path}")
    avg_txhashes = float(avg_txhashes_match.group(1))

    avg_time_match = re.search(r'Average Time per Tick: ([\d.]+)', content)
    if not avg_time_match:
        raise ValueError(f"Could not find average time per tick in {file_path}")
    avg_time = float(avg_time_match.group(1))

    tps_match = re.search(r'Number Of Transfers Per Second \(TPS\): ([\d.]+)', content)
    if not tps_match:
        raise ValueError(f"Could not find TPS in {file_path}")
    tps = float(tps_match.group(1))
    
    # Extract tick distribution with more robust regex
    tick_pattern = r'Tick: (\d+), TxHashes: (\d+)'
    tick_matches = re.finditer(tick_pattern, content)
    tick_distribution = {}
    for match in tick_matches:
        tick = int(match.group(1))
        txhashes = int(match.group(2))
        tick_distribution[tick] = txhashes
    
    if not tick_distribution:
        raise ValueError(f"Could not find any tick distributions in {file_path}")
    
    # Calculate max and min txhashes
    txhashes_counts = list(tick_distribution.values())
    max_txhashes = max(txhashes_counts)
    min_txhashes = min(txhashes_counts)
    
    return BenchmarkMetrics(
        test_start_time=test_start_time,
        test_end_time=test_end_time,
        timestamp=timestamp,
        start_tick=start_tick,
        end_tick=end_tick,
        total_unique_txs=total_unique_txs,
        total_ticks=total_ticks,
        total_txhashes=total_txhashes,
        avg_txhashes_per_tick=avg_txhashes,
        avg_time_per_tick=avg_time,
        tps=tps,
        max_txhashes=max_txhashes,
        min_txhashes=min_txhashes,
        tick_distribution=tick_distribution
    )

def compare_logs(*log_files: str) -> None:
    """Compare performance metrics from multiple benchmark log files"""
    if len(log_files) < 2:
        raise ValueError("At least two log files are required for comparison")
    
    # Parse all log files
    metrics = []
    for file in log_files:
        try:
            metric = parse_log_file(file)
            metrics.append((file, metric))
        except Exception as e:
            print(f"Error parsing file {file}: {e}")
            continue
    
    # Sort metrics by TPS in descending order
    metrics.sort(key=lambda x: x[1].tps, reverse=True)
    best_metric = metrics[0][1]
    
    # Prepare comparison data
    comparison_data = []
    headers = ['Metric'] + [f'Test {i+1}\n({m.timestamp.strftime("%Y%m%d_%H%M%S")})' 
                           for i, (_, m) in enumerate(metrics)]
    
    # Time information
    comparison_data.append(['Time Information', *[''] * (len(metrics))])
    time_metrics = [
        ('  Test Start Time', lambda m: m.test_start_time.strftime('%Y-%m-%d %H:%M:%S')),
        ('  Test End Time', lambda m: m.test_end_time.strftime('%Y-%m-%d %H:%M:%S')),
        ('  Test Duration', lambda m: f"{(m.test_end_time - m.test_start_time).total_seconds():.2f}s"),
        ('  File Timestamp', lambda m: m.timestamp.strftime('%Y-%m-%d %H:%M:%S')),
    ]
    
    for metric_name, metric_func in time_metrics:
        row = [metric_name]
        for _, metric in metrics:
            row.append(metric_func(metric))
        comparison_data.append(row)
    
    # Tick information
    comparison_data.append(['Tick Information', *[''] * (len(metrics))])
    tick_metrics = [
        ('  Start Tick', lambda m: m.start_tick),
        ('  End Tick', lambda m: m.end_tick),
        ('  Tick Range', lambda m: m.end_tick - m.start_tick),
    ]
    
    for metric_name, metric_func in tick_metrics:
        row = [metric_name]
        for _, metric in metrics:
            row.append(metric_func(metric))
        comparison_data.append(row)
    
    # Performance metrics
    comparison_data.append(['Performance Metrics', *[''] * (len(metrics))])
    performance_metrics = [
        ('  Total Unique TxHashes', lambda m: m.total_unique_txs),
        ('  Total Ticks', lambda m: m.total_ticks),
        ('  Total TxHashes', lambda m: m.total_txhashes),
        ('  Avg TxHashes/Tick', lambda m: f"{m.avg_txhashes_per_tick:.2f}"),
        ('  Avg Time/Tick (s)', lambda m: f"{m.avg_time_per_tick:.2f}"),
        ('  TPS', lambda m: f"{m.tps:.2f}"),
        ('  Max TxHashes in Tick', lambda m: m.max_txhashes),
        ('  Min TxHashes in Tick', lambda m: m.min_txhashes),
    ]
    
    for metric_name, metric_func in performance_metrics:
        row = [metric_name]
        for _, metric in metrics:
            row.append(metric_func(metric))
        comparison_data.append(row)
    
    # Relative differences vs best TPS
    comparison_data.append([f'Relative Differences (vs Best TPS: {best_metric.tps:.2f})', *[''] * (len(metrics))])
    percentage_metrics = [
        ('  Total Unique TxHashes', lambda m: m.total_unique_txs),
        ('  TPS', lambda m: m.tps),
        ('  Avg TxHashes/Tick', lambda m: m.avg_txhashes_per_tick),
    ]
    
    for metric_name, metric_func in percentage_metrics:
        row = [metric_name]
        base_value = metric_func(best_metric)
        for _, metric in metrics:
            current_value = metric_func(metric)
            diff_percent = ((current_value - base_value) / base_value) * 100
            row.append(f"{diff_percent:+.2f}%")
        comparison_data.append(row)
    
    # Print comparison table
    print("\nBenchmark Comparison (Sorted by TPS):")
    print(tabulate(comparison_data, headers=headers, tablefmt='grid'))
    
    # Generate distribution statistics
    print("\nTransaction Distribution Statistics:")
    for i, (_, metric) in enumerate(metrics):
        txhashes = list(metric.tick_distribution.values())
        df = pd.Series(txhashes)
        stats = df.describe()
        
        print(f"\nTest {i+1} ({metric.timestamp.strftime('%Y%m%d_%H%M%S')}):")
        print(f"Test Duration: {(metric.test_end_time - metric.test_start_time).total_seconds():.2f}s")
        print(f"TPS: {metric.tps:.2f}")
        print(f"Sample Count: {stats['count']:.0f}")
        print(f"Mean: {stats['mean']:.2f}")
        print(f"Std Dev: {stats['std']:.2f}")
        print(f"Min: {stats['min']:.0f}")
        print(f"25th Percentile: {stats['25%']:.0f}")
        print(f"Median: {stats['50%']:.0f}")
        print(f"75th Percentile: {stats['75%']:.0f}")
        print(f"Max: {stats['max']:.0f}")
    
def main():
    parser = argparse.ArgumentParser(description='Qubic benchmark test and log analysis')
    
    subparsers = parser.add_subparsers(dest='command', help='available commands')
    
    # Test command
    test_parser = subparsers.add_parser('test', help='run benchmark test')
    test_parser.add_argument('-d', '--duration', type=int, required=True,
                          help='test duration in minutes')
    test_parser.add_argument('-n', '--num-accounts', type=int, required=True,
                          help='number of accounts to transfer in single tx')
    test_parser.add_argument('-v', '--verify', action='store_true',
                          help='verify transaction hashes during test')
    
    # Verify command
    verify_parser = subparsers.add_parser('verify', help='verify transaction hashes from file')
    verify_parser.add_argument('-f', '--file', type=str, required=True,
                            help='JSON file to verify')
    
    # Compare command
    compare_parser = subparsers.add_parser('compare', help='compare benchmark log files')
    compare_parser.add_argument('log_files', nargs='+',
                             help='log files to compare (minimum 2 files)')
    
    args = parser.parse_args()
    
    if args.command == 'test':
        loadtest(args.duration, args.num_accounts, args.verify)
    elif args.command == 'verify':
        verifytickhashes(args.file)
    elif args.command == 'compare':
        if len(args.log_files) < 2:
            parser.error("At least two log files are required for comparison")
        compare_logs(*args.log_files)
    else:
        parser.print_help()
if __name__ == "__main__":
    main()
