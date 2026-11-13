import json
import sqlite3
from pathlib import Path

from db.connection import connect
from db.connection import database_path

def init_db_from_schema(db_path, schema_path):
    try:
        conn = None

        # Connect to the SQLite database (it will be created if it doesn't exist).
        # Using the shared helper also stamps the file with WAL mode on creation.
        conn = connect(db_path)

        # Read the SQL schema from the file
        with open(schema_path, 'r') as schema_file:
            sql_script = schema_file.read()

        # Execute the SQL schema to create tables
        conn.executescript(sql_script)

        # Commit the changes and close the connection
        conn.commit()
        
        print(f"Database initialized successfully at {db_path}")

    except FileNotFoundError:
        print(f"Schema file not found: {schema_path}")    

    except sqlite3.Error as e:
        print(f"An error occurred while initializing the database: {e}")

    finally:
        if conn:
            conn.close()

if __name__ == "__main__":

    HERE = Path(__file__).resolve().parent

    db_path = database_path()
    schema_path = HERE / 'job-tracker.sql'

    init_db_from_schema(db_path, schema_path)
