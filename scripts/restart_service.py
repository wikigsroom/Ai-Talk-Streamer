"""Restart only a recorded service of this avatar project."""
import sys
from launch import stop_services,start_service
name=sys.argv[1]
if name not in ('tts','avatar'):raise SystemExit('Unsupported service')
stop_services(name)
start_service(name)
