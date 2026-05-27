import gzip
import os
import shutil
import sys
import tempfile
from pathlib import Path

def decompress_gz(input_file, output_file):
    output_path = Path(output_file)
    temp_path = None
    try:
        with gzip.open(input_file, 'rb') as f_in:
            with tempfile.NamedTemporaryFile('wb', delete=False, dir=output_path.parent or None) as f_out:
                temp_path = Path(f_out.name)
                shutil.copyfileobj(f_in, f_out)
        os.replace(temp_path, output_path)
        print(f"Successfully decompressed {input_file} to {output_file}")
    except Exception as e:
        if temp_path and temp_path.exists():
            temp_path.unlink()
        raise RuntimeError(f"Could not decompress {input_file} to {output_file}") from e


def main():
    try:
        decompress_gz('C:/Users/USER/dbip-city-lite.mmdb.gz', 'C:/Users/USER/dbip-city-lite.mmdb')
    except RuntimeError as e:
        print(f"Error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
