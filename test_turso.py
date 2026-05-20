import libsql_client
client = libsql_client.create_client_sync("file:local_turso.db")
rs = client.execute("SELECT * FROM test")
print("asdict:", rs.rows[0]._asdict())
client.close()
