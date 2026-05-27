import gzip
import shutil
import sys

def decompress_gz(input_file, output_file):
    try:
        with gzip.open(input_file, 'rb') as f_in:
            with open(output_file, 'wb') as f_out:
                shutil.copyfileobj(f_in, f_out)
        print(f"Successfully decompressed {input_file} to {output_file}")
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    decompress_gz('C:/Users/USER/dbip-city-lite.mmdb.gz', 'C:/Users/USER/dbip-city-lite.mmdb')
