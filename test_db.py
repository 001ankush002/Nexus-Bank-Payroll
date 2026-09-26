import os
import mysql.connector
import config

pw = config.DB_CONFIG["password"]
print("User          :", config.DB_CONFIG["user"])
print("Password len  :", len(pw), "(space ya extra character to nahi?)")
print("Windows env   :", "DB_PASSWORD set hai (ye .env ko override kar sakta hai)"
      if "DB_PASSWORD" in os.environ else "DB_PASSWORD set nahi hai")

try:
    con = mysql.connector.connect(**config.DB_CONFIG)
    print("✅ Connected!")
    con.close()
except Exception as e:
    print("❌ Error:", e)