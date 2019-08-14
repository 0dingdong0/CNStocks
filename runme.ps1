# Start-Sleep -Seconds 30

D:
cd D:\workspace\python\

. .\venv_3.7.4\Scripts\activate.ps1
cd CNStocks

python download_hq.py

# shutdown -t 60 -s -f