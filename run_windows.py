"""Select the purchased local Parquet file, convert it and open the chart."""
from datetime import datetime
from pathlib import Path
import sys
import tkinter as tk
from tkinter import filedialog
import webbrowser

from archive_import import convert


def main():
    root = tk.Tk()
    root.withdraw()
    root.attributes('-topmost', True)
    try:
        source = filedialog.askopenfilename(
            title='Select xyz_BRENTOIL trades Parquet',
            filetypes=[('Parquet export', '*.parquet')])
    finally:
        root.destroy()
    if not source:
        print('No file selected. Nothing was processed.')
        return
    output = Path(__file__).resolve().parent / 'results' / datetime.now().strftime('%Y%m%d_%H%M%S')
    result = convert(source, output)
    print(f"Input fill rows: {result['input_fill_rows']}; unique trades: {result['unique_trade_ids']}")
    print('The chart will open in your browser. Files remain in:', output)
    webbrowser.open((output / 'brent_1m.html').as_uri())


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        sys.exit(f'Conversion failed: {exc}\nSource Parquet is unchanged.')
