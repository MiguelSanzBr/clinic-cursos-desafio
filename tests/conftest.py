import os

os.environ["CLINIC_DB"] = ":memory:"  # antes de algum teste importar app.main, que abre o banco no import
