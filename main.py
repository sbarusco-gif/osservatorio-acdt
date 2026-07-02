import os, uuid, shutil, json, fitz, openai
from typing import List
from fastapi import FastAPI, Depends, UploadFile, File, BackgroundTasks, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
import models, schemas, database

app = FastAPI(title="Osservatorio ACDT v7")

app.add_middleware(
    CORSMiddleware,
    allow_ori
