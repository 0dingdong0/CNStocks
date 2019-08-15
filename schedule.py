from libs.tradingday import TradingDay
from config import config

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler import events
from datetime import datetime
from datetime import timedelta

def schedule_jobs():
    if trading_day.is_today_trading_day:
        now = datetime.now()
        start_0 = now.replace(hour=9, minute=14, second=55, microsecond=0)
        end_0 = now.replace(hour=9, minute=25, second=15, microsecond=0)
        
        start_1 = now.replace(hour=9, minute=29, second=55, microsecond=0)
        end_1 = now.replace(hour=11, minute=30, second=15, microsecond=0)
        
        start_2 = now.replace(hour=12, minute=59, second=55, microsecond=0)
        end_2 = now.replace(hour=15, minute=0, second=15, microsecond=0)
        
        job_ids = list([job.id for job in scheduler.get_jobs()])
        
        if now < end_0 and 'hq_beat_0' not in job_ids:
            hq_beat_0 = scheduler.add_job(trading_day.beat, 'interval', id='hq_beat_0', seconds=5, start_date=start_0, end_date=end_0)
        if now < end_1 and 'hq_beat_1' not in job_ids:
            hq_beat_1 = scheduler.add_job(trading_day.beat, 'interval', id='hq_beat_1', seconds=5, start_date=start_1, end_date=end_1)
        if now < end_2 and 'hq_beat_2' not in job_ids:
            hq_beat_2 = scheduler.add_job(trading_day.beat, 'interval', id='hq_beat_2', seconds=5, start_date=start_2, end_date=end_2)
        
        if now < end_2+timedelta(seconds=30) and 'hq_end_2' not in job_ids:
            hq_end_2 = scheduler.add_job(trading_day.save, 'date', id='hq_end_2', run_date=end_2+timedelta(seconds=30))

def event_handler(event):
    if event.code == events.EVENT_JOB_EXECUTED:
        print('job executed:', event.job_id)
        if event.job_id == 'hq_reset':
            schedule_jobs()
    elif event.code == events.VENT_JOB_ERROR:
        print('The job['+event.jod_id+'] crashed :(')
        print(event.exception )
    elif event.code == events.EVENT_JOB_MISSED:
        print('The job['+event.jod_id+'] missed :(')
    else:
        pass

if __name__=="__main__":
    scheduler = BackgroundScheduler()
    scheduler.add_listener(event_handler, events.EVENT_JOB_EXECUTED | events.EVENT_JOB_ERROR | events.EVENT_JOB_MISSED)
    scheduler.start()

    trading_day = TradingDay(
        tdx_root=config.tdx_root, 
        concurrency=config.concurrency, 
        sub_group_count=config.sub_group_count
    )

    hq_reset = scheduler.add_job(
        trading_day.reset, 
        'cron', 
        id='hq_reset', 
        day_of_week='mon-fri', 
        hour=9, 
        minute=2
    )
