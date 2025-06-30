import os
import xml.etree.ElementTree as ET
import pandas as pd

from dataset import data_dir

def parse_tasks(xml_file):
    tree = ET.parse(xml_file)
    root = tree.getroot()

    # Navigate to the tasks node
    tasks = {}
    for task in root.findall(".//task"):
        task_data = {
            "name": task.find("name").text,
            "size": int(task.find("size").text),
            "start_frame": int(task.find("start_frame").text),
            "stop_frame": int(task.find("stop_frame").text),
            "resolution": {
                "width": int(task.find("original_size/width").text),
                "height": int(task.find("original_size/height").text)
            }
        }
        tasks[int(task.find("id").text)] = task_data

    return tasks

def parse_tasks(xml_file):
    tree = ET.parse(xml_file)
    root = tree.getroot()

    # Navigate to the tasks node
    tasks = {}
    for task in root.findall(".//task"):
        task_data = {
            "name": task.find("name").text,
            "size": int(task.find("size").text),
            "start_frame": int(task.find("start_frame").text),
            "stop_frame": int(task.find("stop_frame").text),
            "resolution": {
                "width": int(task.find("original_size/width").text),
                "height": int(task.find("original_size/height").text)
            }
        }
        tasks[int(task.find("id").text)] = task_data

    return tasks

def parse_tracks(match_dir_path):
    print(match_dir_path)
    for xml_filename in os.listdir(os.path.join(match_dir_path, "annotations")):
        xml_file = os.path.join(match_dir_path, "annotations", xml_filename)
        tree = ET.parse(xml_file)
        root = tree.getroot()

        task_data = parse_tasks(xml_file)
        print(task_data)
        
        last_start_frame_actual = 0
        last_size = 0
        for task_id in task_data:
            if last_size == 0:
                task_data[task_id]['start_frame_actual'] = 0
                last_start_frame_actual = task_data[task_id]['start_frame_actual']
                last_size = task_data[task_id]['size']
            else:
                task_data[task_id]['start_frame_actual'] = last_start_frame_actual + last_size
                last_start_frame_actual = task_data[task_id]['start_frame_actual']
                last_size = task_data[task_id]['size']

        for track in root.findall(".//track"):
            track_info = track.attrib
            print(track_info)
            frames = []
            start_frame = None
            tracking_outside = 0
            for point in track.iter('points'):
                point_info = point.attrib

                # init the start_frame of the track
                if start_frame == None:
                    start_frame = int(task_data[int(track_info['task_id'])]['start_frame_actual'])
                    # If the calculated start frame (actual) does not equal the first point, then the clip starts with the ball outside
                    if start_frame != int(point_info['frame']):
                        tracking_outside = 1
                        outside_start_frame = 0

                if point_info['outside'] == '1':
                    if tracking_outside == 0:
                        tracking_outside = 1
                        outside_start_frame = int(point_info['frame'])-start_frame   
                else:
                    # Add in all the frames the ball was not visible for
                    if tracking_outside == 1:
                        #print(outside_start_frame, int(point_info['frame'])-start_frame)
                        #print(int(point_info['frame']), start_frame)
                        for i in range(outside_start_frame, int(point_info['frame'])-start_frame):
                            #print(i, 0, 0.0, 0.0)
                            frames.append({
                                "Frame":i,
                                "Visibility":0, # flipping 0's and 1's
                                "X":0.0,
                                "Y":0.0
                            })
                        tracking_outside = 0
                        outside_start_frame = 0
                    #print(int(point_info['frame'])-start_frame, 1, float(point_info['points'].split(',')[0]), float(point_info['points'].split(',')[1]))
                    frames.append({
                        "Frame":int(point_info['frame'])-start_frame,
                        "Visibility":1, # flipping 0's and 1's
                        "X":float(point_info['points'].split(',')[0]),
                        "Y":float(point_info['points'].split(',')[1])
                    })
            
            # If ends on an outside point
            if tracking_outside == 1:
                #print(outside_start_frame, int(point_info['frame'])-start_frame)
                #print(int(point_info['frame']), start_frame)
                for i in range(outside_start_frame, task_data[int(track_info['task_id'])]['size']):
                    #print(i, 0, 0.0, 0.0)
                    frames.append({
                        "Frame":i,
                        "Visibility":0, # flipping 0's and 1's
                        "X":0.0,
                        "Y":0.0
                    })
                tracking_outside = 0
                outside_start_frame = 0
                    

            name, ext = task_data[int(track.attrib['task_id'])]['name'].rsplit('.', 1)
            file_name = f"{name}_ball.csv"
            
            csv_dir_path = os.path.join(match_dir_path, 'csv')
            os.makedirs(csv_dir_path, exist_ok=True)
            
            df = pd.DataFrame(frames)
            df.to_csv(os.path.join(csv_dir_path, file_name), index=False)
            print(os.path.join(csv_dir_path, file_name))

for match_dir in os.listdir(os.path.join(data_dir, "train")):
    match_dir_path = os.path.join(data_dir, "train", match_dir)
    parse_tracks(match_dir_path)