#!/usr/bin/env python3
"""
    Project Edenbridge
    Copyright (C) 2019 - 2020  Zhengyu Peng

    This program is free software: you can redistribute it and/or modify
    it under the terms of the GNU General Public License as published by
    the Free Software Foundation, either version 3 of the License, or
    (at your option) any later version.

    This program is distributed in the hope that it will be useful,
    but WITHOUT ANY WARRANTY; without even the implied warranty of
    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
    GNU General Public License for more details.

    You should have received a copy of the GNU General Public License
    along with this program.  If not, see <https://www.gnu.org/licenses/>.
"""

from threading import Thread
from pathlib import Path
import os
import picamera
from picamera.array import PiRGBArray
import datetime
import queue
import copy
import logging

import imutils
import cv2
import time


class Camera(Thread):
    def __init__(self, config, q2camera, q2mbot, q2cloud):
        Thread.__init__(self)
        self.config = config
        self.cwd = Path().absolute()
        self.motion2camera = q2camera
        self.q2mbot = q2mbot
        self.q2cloud = q2cloud

        self.max_photo_count = config['max_photo_count']
        self.max_video_count = config['max_video_count']
        self.period = config['period']
        self.video_length = config['video_length']
        self.video_path = str(self.cwd) + '/videos/'
        self.photo_path = str(self.cwd) + '/photos/'

        self.det_resolution = tuple(config['detection_resolution'])
        self.rec_resolution = tuple(config['record_resolution'])

        self.delta_thresh = config['delta_thresh']
        self.min_area = config['min_area']
        self.motion_frame_counter = 0

        # initialize the camera and grab a reference to the raw camera capture
        # camera.resolution = tuple(conf["resolution"])
        # camera.framerate = conf["fps"]
        self.camera = picamera.PiCamera(resolution=self.det_resolution)
        self.raw_capture = PiRGBArray(
            self.camera,
            size=tuple(self.det_resolution))

        # allow the camera to warmup, then initialize the average frame, last
        # uploaded timestamp, and frame motion counter
        print("[INFO] warming up...")
        time.sleep(config["camera_warmup_time"])
        self.avg_capture = None
        # lastUploaded = datetime.datetime.now()
        # self.motionCounter = 0

        try:
            os.makedirs(self.video_path)
        except FileExistsError:
            pass

        try:
            os.makedirs(self.photo_path)
        except FileExistsError:
            pass

        self.cmd_upload_h264 = {
            'cmd': 'upload_file',
            'path': self.video_path,
            'file_type': 'H264',
            'file_name': '',
            'extension': '.h264',
            'date': '',
            'time': ''
        }

        self.cmd_send_jpg = {
            'cmd': 'send_photo',
            'path': self.photo_path,
            'file_type': 'JPG',
            'file_name': '',
            'extension': '.jpg',
            'date': '',
            'time': ''
        }

    def take_photo(self, counts, period):
        self.camera.resolution = self.rec_resolution

        if counts == 0 or counts > self.max_photo_count:
            counts = self.max_photo_count

        for photo_idx in range(0, counts):
            date_str = datetime.datetime.now().strftime('%Y-%m-%d')
            time_str = datetime.datetime.now().strftime('%H-%M-%S')

            self.cmd_send_jpg['date'] = date_str
            self.cmd_send_jpg['time'] = time_str
            self.cmd_send_jpg[
                'file_name'] = date_str + '_' + time_str + '_' + 'photo' + str(
                    photo_idx)

            self.camera.capture(self.cmd_send_jpg['path'] +
                                self.cmd_send_jpg['file_name'] +
                                self.cmd_send_jpg['extension'])
            self.q2mbot.put(copy.deepcopy(self.cmd_send_jpg))

            try:
                msg = self.motion2camera.get(block=True, timeout=period)
            except queue.Empty:
                pass
            else:
                if msg['cmd'] is 'stop':
                    self.motion2camera.task_done()
                    logging.info('Stop capturing')
                    break
                else:
                    self.motion2camera.task_done()
                    logging.warning('Wrong command, continue capturing')
                pass

    def take_video(self, count, init_photo=True):
        self.camera.resolution = self.rec_resolution
        if count == 0 or count > self.max_video_count:
            count = self.max_video_count

        def take_photo_during_recording(video_idx, date, time):
            for photo_idx in range(0, int(self.video_length / self.period)):
                try:
                    msg = self.motion2camera.get(block=True,
                                                 timeout=self.period)
                except queue.Empty:
                    date_str = datetime.datetime.now().strftime('%Y-%m-%d')
                    time_str = datetime.datetime.now().strftime('%H-%M-%S')
                    self.cmd_send_jpg['file_name'] = date_str + \
                        '_' + \
                        time_str + \
                        '_' + \
                        'photo' + \
                        str(
                        int(1 + photo_idx + video_idx *
                            int(self.video_length / self.period)))
                    self.cmd_send_jpg['date'] = date_str
                    self.cmd_send_jpg['time'] = time_str
                    self.camera.capture(self.cmd_send_jpg['path'] +
                                        self.cmd_send_jpg['file_name'] +
                                        self.cmd_send_jpg['extension'],
                                        use_video_port=True)
                    self.q2mbot.put(copy.deepcopy(self.cmd_send_jpg))
                    pass
                else:
                    if msg['cmd'] is 'stop':
                        self.camera.stop_recording()
                        self.motion2camera.task_done()

                        self.q2cloud.put(copy.deepcopy(self.cmd_upload_h264))

                        logging.info('Stop recording')
                        return 1
                    else:
                        self.motion2camera.task_done()
                        logging.warning('Wrong command, continue recording')
                    pass
            return 0

        date_str = datetime.datetime.now().strftime('%Y-%m-%d')
        time_str = datetime.datetime.now().strftime('%H-%M-%S')
        self.cmd_upload_h264['file_name'] = time_str + '_' + 'video' + str(0)
        self.cmd_upload_h264['date'] = date_str
        self.cmd_upload_h264['time'] = time_str

        self.cmd_send_jpg[
            'file_name'] = date_str + '_' + time_str + '_' + 'photo' + str(0)
        self.cmd_send_jpg['date'] = date_str
        self.cmd_send_jpg['time'] = time_str

        self.camera.start_recording(self.cmd_upload_h264['path'] +
                                    self.cmd_upload_h264['file_name'] +
                                    self.cmd_upload_h264['extension'])
        if init_photo:
            self.camera.capture(self.cmd_send_jpg['path'] +
                                self.cmd_send_jpg['file_name'] +
                                self.cmd_send_jpg['extension'],
                                use_video_port=True)
            self.q2mbot.put(copy.deepcopy(self.cmd_send_jpg))

        if take_photo_during_recording(0, date_str, time_str) == 1:
            return

        if count > 1:

            for video_idx in range(1, count):
                date_str = datetime.datetime.now().strftime('%Y-%m-%d')
                time_str = datetime.datetime.now().strftime('%H-%M-%S')

                temp_cmd = copy.deepcopy(self.cmd_upload_h264)

                self.cmd_upload_h264[
                    'file_name'] = time_str + '_' + 'video' + str(video_idx)
                self.cmd_upload_h264['date'] = date_str
                self.cmd_upload_h264['time'] = time_str
                self.camera.split_recording(self.cmd_upload_h264['path'] +
                                            self.cmd_upload_h264['file_name'] +
                                            self.cmd_upload_h264['extension'])

                self.q2cloud.put(temp_cmd)

                if take_photo_during_recording(video_idx, date_str,
                                               time_str) == 1:
                    return

            self.camera.stop_recording()
            self.q2cloud.put(copy.deepcopy(self.cmd_upload_h264))

        else:
            self.camera.stop_recording()
            self.q2cloud.put(copy.deepcopy(self.cmd_upload_h264))

    def motion_detection(self):
        self.camera.resolution = self.det_resolution
        self.avg_capture = None
        self.motion_frame_counter = 0
        is_occupied = False

        # capture frames from the camera
        for frm in self.camera.capture_continuous(
                self.raw_capture, format="bgr", use_video_port=True):
            # grab the raw NumPy array representing the image and initialize
            # the timestamp and occupied/unoccupied text
            frame = frm.array

            # clear the stream in preparation for the next frame
            self.raw_capture.truncate(0)
            text = "Unoccupied"

            # resize the frame, convert it to grayscale, and blur it
            frame = imutils.resize(frame, width=500)
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            gray = cv2.GaussianBlur(gray, (21, 21), 0)

            # if the average frame is None, initialize it
            if self.avg_capture is None:
                print("[INFO] starting background model...")
                self.avg_capture = gray.copy().astype("float")
                # self.raw_capture.truncate(0)
                continue

            # accumulate the weighted average between the current frame and
            # previous frames, then compute the difference between the current
            # frame and running average
            cv2.accumulateWeighted(gray, self.avg_capture, 0.5)
            frame_delta = cv2.absdiff(
                gray, cv2.convertScaleAbs(self.avg_capture))

            # threshold the delta image, dilate the thresholded image to fill
            # in holes, then find contours on thresholded image
            thresh = cv2.threshold(frame_delta, self.delta_thresh, 255,
                                   cv2.THRESH_BINARY)[1]
            thresh = cv2.dilate(thresh, None, iterations=2)
            contours = cv2.findContours(thresh.copy(), cv2.RETR_EXTERNAL,
                                        cv2.CHAIN_APPROX_SIMPLE)
            contours = imutils.grab_contours(contours)

            # loop over the contours
            for contr in contours:
                # if the contour is too small, ignore it
                if cv2.contourArea(contr) < self.min_area:
                    continue

                date_str = datetime.datetime.now().strftime('%Y-%m-%d')
                time_str = datetime.datetime.now().strftime('%H-%M-%S')
                # draw box and timestamp on frame
                (x, y, w, h) = cv2.boundingRect(contr)
                cv2.rectangle(frame, (x, y), (x + w, y + h), (0, 255, 0), 1)
                cv2.putText(frame, 'Front Door', (10, 25),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 1)
                cv2.putText(frame, date_str + '_' + time_str,
                            (10, frame.shape[0] - 10),
                            cv2.FONT_HERSHEY_SIMPLEX,
                            0.5, (0, 0, 255), 1)

                self.cmd_send_jpg['date'] = date_str
                self.cmd_send_jpg['time'] = time_str
                self.cmd_send_jpg['file_name'] = date_str + '_' + time_str

                cv2.imwrite(self.cmd_send_jpg['path'] +
                            self.cmd_send_jpg['file_name'] +
                            self.cmd_send_jpg['extension'],
                            frame)
                self.q2mbot.put(copy.deepcopy(self.cmd_send_jpg))

                is_occupied = True
                return is_occupied

            self.motion_frame_counter += 1
            if self.motion_frame_counter >= 10:
                return is_occupied

    def run(self):
        logging.info('Camera thread started')
        print('Camera thread started')
        while True:
            status = self.motion_detection()
            print(status)
            if status:
                self.take_video(1, init_photo=False)
            else:
                # time.sleep(3)
                # retrieve data (blocking)
                try:
                    msg = self.motion2camera.get(block=True, timeout=None)
                    if msg['cmd'] is 'take_photo':
                        self.motion2camera.task_done()
                        self.take_photo(msg['count'], self.period)
                        logging.info('Start to capture photos')
                    elif msg['cmd'] is 'take_video':
                        self.motion2camera.task_done()
                        self.take_video(msg['count'])
                        logging.info('Start to record videos')
                    else:
                        self.motion2camera.task_done()
                except queue.Empty:
                    pass


'''

    `                      `
    -:.                  -#:
    -//:.              -###:
    -////:.          -#####:
    -/:.://:.      -###++##:
    ..   `://:-  -###+. :##:
           `:/+####+.   :##:
    .::::::::/+###.     :##:
    .////-----+##:    `:###:
     `-//:.   :##:  `:###/.
       `-//:. :##:`:###/.
         `-//:+######/.
           `-/+####/.
             `+##+.
              :##:
              :##:
              :##:
              :##:
              :##:
               .+:

'''
