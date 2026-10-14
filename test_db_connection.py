import streamlit as st
import mysql.connector

try:
    config = st.secrets["mysql"]

    conn = mysql.connector.connect(
        host=config["host"],
        port=config["port"],
        user=config["user"],
        password=config["password"],
        database=config["database"],
        connection_timeout=5,
    )

    if conn.is_connected():
        print("SUCCESS: Connected to MySQL!")
        print("Database:", config["database"])

        cursor = conn.cursor()
        cursor.execute("SHOW TABLES")
        tables = cursor.fetchall()

        print("Tables found:")
        for table in tables:
            print("-", table[0])

        cursor.close()
        conn.close()

except Exception as e:
    print("CONNECTION FAILED")
    print(type(e).__name__ + ":", e)