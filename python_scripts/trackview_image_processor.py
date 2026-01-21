import boto3
import botocore
from botocore.client import Config
import inspect
import itertools
import json
import math
import os
import tempfile
import cv2
import geopandas as gpd
import numpy as np
import orthority as oty
import pandas as pd
import re
import rioxarray
from shapely import *
from smart_open import open as smart_open
import xarray as xr
import scipy
from PIL import Image
from PIL.ExifTags import TAGS, GPSTAGS
from concurrent.futures import ThreadPoolExecutor, as_completed
from pystac_client import Client

from geocube.api.core import make_geocube


from scipy import ndimage
import utm
import mercantile


import numpy as np
import xarray as xr
from shapely.geometry import box, Polygon


from libxmp import XMPFiles, consts
from libxmp.utils import file_to_dict
import tempfile

import os
import boto3
from botocore.exceptions import NoCredentialsError, ClientError
from urllib.parse import urlparse




import numpy as np
import math

def ypr_to_opk(yaw_deg, pitch_deg, roll_deg):
    """
    Convert aircraft Yaw, Pitch, Roll (YPR) to Omega, Phi, Kappa (OPK).

    Aircraft frame (body): X forward, Y right, Z down.
    Reference frame (nav): X north, Y east, Z up.

    Args:
        yaw_deg (float): Yaw angle in degrees.
        pitch_deg (float): Pitch angle in degrees.
        roll_deg (float): Roll angle in degrees.

    Returns:
        tuple: (omega_deg, phi_deg, kappa_deg) angles in degrees.
    """
    # Convert degrees to radians
    yaw = np.deg2rad(yaw_deg)
    pitch = np.deg2rad(pitch_deg)
    roll = np.deg2rad(roll_deg)

    # 1. Create the rotation matrix from the navigation frame (NED: X North, Y East, Z Down) to the body frame.
    # Standard aircraft convention uses a ZYX rotation sequence for yaw, pitch, roll.
    R_nav_to_body = rotation_matrix_zyx(yaw, pitch, roll)

    # 2. Adjust for the target reference frame where Z is UP.
    # The standard navigation frame has Z pointing down (NED). We need to transform
    # the rotation matrix to a frame where Z is up. This requires an additional
    # transformation. The simplest way is to transform the final rotation matrix
    # to be in the target "Z-up" reference system.
    
    # A common transformation matrix for this purpose (from Pix4D notes, adapted)
    # is T = [(-1,0,0),(0,1,0),(0,0,-1)] to flip the X and Z axes to match standard photogrammetry conventions.
    T = np.array([[-1, 0, 0],
                  [0, 1, 0],
                  [0, 0, -1]])
    
    # The final rotation matrix from the "Z-up" frame to the body frame (or similar).
    # The exact relationship depends on specific photogrammetry definitions, but
    # a common one for Pix4D workflow is R_OPK = T @ R_YPR.
    R_OPK_frame = T @ R_nav_to_body @ T # Re-orient the rotation into the target frame

    # 3. Extract Omega (omega), Phi (phi), Kappa (kappa) from the resulting matrix.
    # Omega, Phi, Kappa typically follow an X-Y-Z rotation sequence (ω around X, φ around Y, κ around Z).
    omega, phi, kappa = rotation_matrix_to_opk(R_OPK_frame)

    # Convert radians back to degrees
    omega_deg = np.rad2deg(omega)
    phi_deg = np.rad2deg(phi)
    kappa_deg = np.rad2deg(kappa)

    return omega_deg, phi_deg, kappa_deg

def rotation_matrix_zyx(yaw, pitch, roll):
    """
    Generate a ZYX rotation matrix (used for aircraft YPR).
    """
    Rz = np.array([[np.cos(yaw), -np.sin(yaw), 0],
                   [np.sin(yaw), np.cos(yaw), 0],
                   [0, 0, 1]])
    Ry = np.array([[np.cos(pitch), 0, np.sin(pitch)],
                   [0, 1, 0],
                   [-np.sin(pitch), 0, np.cos(pitch)]])
    Rx = np.array([[1, 0, 0],
                   [0, np.cos(roll), -np.sin(roll)],
                   [0, np.sin(roll), np.cos(roll)]])
    # Order of matrix multiplication is Rz * Ry * Rx for ZYX extrinsic rotations
    return Rz @ Ry @ Rx

def rotation_matrix_to_opk(R_matrix):
    """
    Convert a rotation matrix to Omega, Phi, Kappa angles (XYZ sequence, intrinsic).
    Handles potential gimbal lock issues near pitch +/- 90 degrees.
    """
    r11, r12, r13 = R_matrix[0, 0], R_matrix[0, 1], R_matrix[0, 2]
    r21, r22, r23 = R_matrix[1, 0], R_matrix[1, 1], R_matrix[1, 2]
    r31, r32, r33 = R_matrix[2, 0], R_matrix[2, 1], R_matrix[2, 2]

    # Standard formulas for extracting XYZ Euler angles
    if abs(r31) >= 1.0:
        phi = np.arcsin(-r31)
        omega = 0.0
        kappa = np.arctan2(r12, r13) if r31 < 0 else np.arctan2(-r12, -r13)
    else:
        phi = np.arcsin(-r31)
        omega = np.arctan2(r32, r33)
        kappa = np.arctan2(r21, r11)

    return omega, phi, kappa









def download_s3_file(s3_full_path: str, local_path: str):
    """
    Downloads a file from S3 to a local path.
    
    :param s3_full_path: Full S3 path (e.g., s3://bucket-name/path/to/file.txt)
    :param local_path: Local file path where the file will be saved
    """
    # Validate S3 path format
    if not s3_full_path.startswith("s3://"):
        raise ValueError("S3 path must start with 's3://'")

    # Parse S3 URL
    parsed_url = urlparse(s3_full_path)
    bucket_name = parsed_url.netloc
    s3_key = parsed_url.path.lstrip("/")

    if not bucket_name or not s3_key:
        raise ValueError("Invalid S3 path format. Example: s3://my-bucket/path/to/file.txt")

    # Ensure local directory exists
    os.makedirs(os.path.dirname(local_path), exist_ok=True)

    # Create S3 client
    s3 = boto3.client("s3")

    try:
        print(f"Downloading from {s3_full_path} to {local_path}...")
        s3.download_file(bucket_name, s3_key, local_path)
        print("✅ Download completed successfully.")
    except FileNotFoundError:
        print("❌ Local path is invalid.")
    except NoCredentialsError:
        print("❌ AWS credentials not found. Configure them using 'aws configure'.")
    except ClientError as e:
        if e.response['Error']['Code'] == "404":
            print("❌ The object does not exist in S3.")
        else:
            print(f"❌ AWS ClientError: {e}")
    except Exception as e:
        print(f"❌ Unexpected error: {e}")


import subprocess
import json

from PIL import Image
from defusedxml import ElementTree as ET
import io

def extract_phaseone_orientation(image_path):
    """
    Extracts Gimbal Yaw, Pitch, and Roll from Phase One XMP metadata.
    Supports .JPG, .TIF, and some .IIQ formats via Pillow.
    """
    with tempfile.NamedTemporaryFile() as temp_file:
        download_s3_file(image_path, temp_file.name)# Read all XMP metadata into a dictionary
            
        
        with Image.open(temp_file.name) as img:
            xmp_data = img.info.get("xmp") or img.info.get("XML:com.adobe.xmp")
        
    if not xmp_data:
        return {"error": "No XMP metadata found in image."}

    # 2. Handle bytes to string conversion
    if isinstance(xmp_data, bytes):
        xmp_str = xmp_data.decode("utf-8", errors="ignore")
    else:
        xmp_str = xmp_data

    # 3. Parse XML safely
    # Note: We strip namespace prefixes for easier dictionary access
    root = ET.fromstring(xmp_str)
    
    # Phase One uses 'GPSIMUYaw', 'GPSIMUPitch', and 'GPSIMURoll'
    # These are usually inside the rdf:Description element
    telemetry = {
        "yaw": None,
        "pitch": None,
        "roll": None
    }

    # Search the XML for the specific Phase One tags
    # These can appear as attributes or nested elements
    for desc in root.iter("{http://www.w3.org}Description"):
        # Check Attributes (common in Phase One XMP)
        attrs = desc.attrib
        telemetry["yaw"] = attrs.get("{http://ns.phaseone.com}GPSIMUYaw") or telemetry["yaw"]
        telemetry["pitch"] = attrs.get("{http://ns.phaseone.com}GPSIMUPitch") or telemetry["pitch"]
        telemetry["roll"] = attrs.get("{http://ns.phaseone.com}GPSIMURoll") or telemetry["roll"]
        telemetry["yaw_ref"] = attrs.get("{http://ns.phaseone.com}GPSIMUYawRef") or telemetry["yaw_ref"]

    # 4. Fallback: Simple string search if XML structure varies
    if not telemetry["yaw"]:
        import re
        for key in ["GPSIMUYaw", "GPSIMUPitch", "GPSIMURoll"]:
            match = re.search("<aerialgps:{}>(?P<numerator>[\-0-9]+)/(?P<denominator>[\-0-9]+)</aerialgps:{}>".format(key, key), xmp_str)
            if match:
                telemetry[key.lower().replace("gpsimu", "")] = float(match.group('numerator'))/float(match.group('denominator'))
    omega, phi, kappa = ypr_to_opk(*[telemetry[key] for key in ['yaw', 'pitch', 'roll']])
    result =  {
            'omega': float(omega),
            'phi': float(phi),
            'kappa': float(kappa)
        }
    return result
        


    






def extract_dji_orientation(image_path):
    """
    Extracts Yaw, Pitch, and Roll from DJI drone image XMP metadata.
    Returns a dictionary with the values or None if not found.
    """
    
    if image_path.startswith('s3://'):
        with tempfile.NamedTemporaryFile() as temp_file:
            download_s3_file(image_path, temp_file.name)# Read all XMP metadata into a dictionary
            xmp_dict = file_to_dict(temp_file.name)
    else:
        xmp_dict = file_to_dict(image_path)

 
    # DJI stores orientation in the 'drone-dji' namespace
    dji_ns = 'http://www.dji.com/drone-dji/1.0/'

    yaw = pitch = roll = None

    # Loop through namespaces and extract values
    for ns, props in xmp_dict.items():
        if ns == dji_ns:
            
            props_dict = {prop[0]: prop[1] for prop in props}
            yaw = float(props_dict.get('drone-dji:FlightYawDegree'))
            pitch = float(props_dict.get('drone-dji:FlightPitchDegree'))
            roll = float(props_dict.get('drone-dji:FlightRollDegree'))
        

    if yaw is not None and pitch is not None and roll is not None:
        omega, phi, kappa = ypr_to_opk(yaw, pitch, roll)   
        result =  {
            'omega': float(omega),
            'phi': float(phi),
            'kappa': float(kappa)
        }
        return result
    else:
        return None
    
    
    
    
def get_gps_info(exif_data):
    if not exif_data or "GPSInfo" not in exif_data:
        return None
    gps_info = {}
    for key in exif_data["GPSInfo"].keys():
        name = GPSTAGS.get(key, key)
        gps_info[name] = exif_data["GPSInfo"][key]
    return gps_info


def convert_to_degrees(value):
    d, m, s = value
    return d + (m / 60.0) + (s / 3600.0)



def extract_exif_data(image_path):
    
    with smart_open(image_path, 'rb') as fp:
        img = Image.open(fp)
        _exif_data = img._getexif()
        px_width, px_height = img.size

    
    if not _exif_data:
        return "No EXIF data found."

    # Map EXIF tags to their names
    exif_data = {TAGS.get(tag): value for tag, value in _exif_data.items()}

    #Get sensor width and folcal length
    focal_length = exif_data.get("FocalLength")
    focal_length_35mm = exif_data.get("FocalLengthIn35mmFilm")
    
    if not focal_length or not focal_length_35mm:
        return "Focal length data not available in EXIF."
    
    # Convert focal length to float (if it's a tuple, e.g., (50, 1) -> 50.0)
    focal_length = focal_length[0] / focal_length[1] if isinstance(focal_length, tuple) else focal_length
    crop_factor = focal_length_35mm / focal_length
    
    # Calculate sensor width
    sensor_width = .036 / crop_factor

     # Calculate sensor width
    sensor_height = .024 / crop_factor

    #convert focal_length to meters
    focal_length = .001 * focal_length # Convert to float

    gps_info = get_gps_info(exif_data)
    if gps_info:
        lat = convert_to_degrees(gps_info["GPSLatitude"])
        if gps_info["GPSLatitudeRef"] != "N":
            lat = -lat
        lon = convert_to_degrees(gps_info["GPSLongitude"])
        if gps_info["GPSLongitudeRef"] != "E":
            lon = -lon
        altitude = gps_info['GPSAltitude']
        position = (lat, lon, altitude)
    else:
        position = None

    # Extract date and time
    _time_string = exif_data.get("DateTimeOriginal", None)
    time_string = _time_string.split()[0].replace(':','-') + ' ' + _time_string.split()[1]
    timestamp = pd.to_datetime(time_string)

    
    
   

    out_dict = {

        'image_path': image_path,
        'timestamp': timestamp, 
        'lat': position[0],
        'lon': position[1],
        'alt' : float(position[2]),
        'focal_length': focal_length, 
        'sensor_width': sensor_width,
        'sensor_height': sensor_height,
        'px_width': px_width,
        'px_height': px_height
    }
    return out_dict




def get_world_boundary(
        x: float,
        y: float,
        alt: float,
        omega: float,
        phi: float,
        kappa: float,
        focal_length: float,
        sensor_width: float,
        sensor_height: float,
        px_width: int,
        px_height: int,
        elevation: float

    ):
        
 

        # Create camera model
        cam_model = oty.camera.FrameCamera(
            focal_len=focal_length,  # convert mm to meters
            sensor_size=(sensor_width, sensor_height),
            im_size = (px_width,px_height),
            xyz = (x, y, alt),
            opk = (omega * math.pi/180, phi* math.pi/180, kappa * math.pi / 180),
        )  
        
        world_boundary = Polygon(cam_model.world_boundary(elevation)[:2,:].transpose())

        return world_boundary




def find_exterior_points(mask: np.ndarray) -> np.ndarray:
    """
    Find exterior (boundary) points of a boolean mask matrix.
    
    Parameters:
        mask (np.ndarray): 2D boolean array where True = inside region, False = outside.
    
    Returns:
        np.ndarray: Boolean array where True = exterior/boundary points.
    """
    if not isinstance(mask, np.ndarray) or mask.dtype != bool:
        raise ValueError("mask must be a 2D NumPy boolean array.")
    if mask.ndim != 2:
        raise ValueError("mask must be a 2D array.")

    # Create a binary structure for connectivity (4-connectivity)
    structure = ndimage.generate_binary_structure(2, 1)

    # Erode the mask to shrink the region
    eroded = ndimage.binary_erosion(mask, structure=structure)

    # Boundary = mask - eroded
    boundary = mask & ~eroded
    return boundary


def convex_hull(data):
    points = np.argwhere(find_exterior_points(data.values > 0))
    hull = scipy.spatial.ConvexHull(points)
    x = data.coords['x'][points[hull.vertices][:,1]]
    y = data.coords['y'][points[hull.vertices][:,0]]
    polygon = Polygon(zip(x,y))
    return polygon


def latlon_to_tms(lat, lon, zoom):
    """
    Convert latitude, longitude, and zoom level to TMS tile coordinates.
    
    Args:
        lat (float): Latitude in degrees (-90 to 90)
        lon (float): Longitude in degrees (-180 to 180)
        zoom (int): Zoom level (0+)
    
    Returns:
        (x, y): TMS tile coordinates as integers
    """
    # Validate inputs
    if not (-90 <= lat <= 90):
        raise ValueError("Latitude must be between -90 and 90 degrees.")
    if not (-180 <= lon <= 180):
        raise ValueError("Longitude must be between -180 and 180 degrees.")
    if not (isinstance(zoom, int) and zoom >= 0):
        raise ValueError("Zoom level must be a non-negative integer.")

    # Convert lat/lon to radians
    lat_rad = math.radians(lat)

    # Number of tiles at this zoom level
    n = 2 ** zoom

    # Convert to Google/XYZ tile coordinates
    x_tile = (lon + 180.0) / 360.0 * n
    y_tile = (1.0 - math.log(math.tan(lat_rad) + (1 / math.cos(lat_rad))) / math.pi) / 2.0 * n

    # Convert XYZ to TMS (flip Y axis)
    #tms_y = n - 1 - int(y_tile)
    tms_y = int(y_tile)

    return int(x_tile), tms_y


def tms_tile_polygon(x, y, z):
    """
    Calculate the boundaries of a TMS tile in Web Mercator projection.
    
    Args:
        x (int): Tile X coordinate.
        y (int): Tile Y coordinate.
        z (int): Zoom level.
    
    Returns:
        dict: A dictionary with the boundaries (min_lon, min_lat, max_lon, max_lat).
    """
    # Number of tiles at the given zoom level
    n = 2 ** z

    # Convert tile coordinates to normalized Web Mercator coordinates
    xmin = x / n * 360.0 - 180.0
    xmax = (x + 1) / n * 360.0 - 180.0

    ymin = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * y / n))))
    ymax = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * (y + 1) / n))))

    polygon = Polygon([(xmin,ymin),(xmin,ymax),(xmax,ymax),(xmax,ymin),(xmin,ymin)])
    return polygon


def tile_gsds(lat, lon, zmin = 18, zmax = 26):
    df_out = pd.DataFrame()
    for z in range(zmin,zmax+1):
        x,y = latlon_to_tms(lat, lon, z)
        tile_polygon = tms_tile_polygon(x,y,z)
        xmin, ymin, xmax, ymax = tile_polygon.bounds
        df_add = pd.DataFrame({'z': [z], 'gsd_x': [(xmax - xmin)/256], 'gsd_y': (ymax - ymin)/256})
        df_out = pd.concat([df_out, df_add])
    return df_out









def orthorectify_image(
    image_path: str,
    dem_path: str,
    x: float,
    y: float,
    minlon: float,
    minlat: float,
    maxlon: float,
    maxlat: float,
    alt: float,
    omega: float,
    phi: float,
    kappa: float,
    focal_length: float,
    sensor_width: float,
    sensor_height: float,
    px_width: int,
    px_height: int,
    crs: str,
    
):
    """
    Orthorectify an aerial image using UAV camera position and orientation.

    Args:
        image_path: Path to UAV image.
        dem_path: Path to DEM (GeoTIFF).
        output_path: Path to save orthorectified image.
        lat, lon, alt: UAV camera position in WGS84.
        yaw, pitch, roll: Camera orientation in degrees.
        focal_length: Camera focal length in m.
        sensor_width, sensor_height_mm: Sensor dimensions in m.
        px_width, px_height: Image resolution in pixels.
    """


    temp_dir = '/tmp'
    temp_image_path = "{}/image.jpg".format(temp_dir)
    command = "aws s3 cp {} {}".format(image_path, temp_image_path)
    print(command)
    os.system(command)

    # Create camera model
    cam_model = oty.camera.FrameCamera(
        focal_len=focal_length,  # convert mm to meters
        sensor_size=(sensor_width, sensor_height),
        im_size = (px_width,px_height),
        xyz = (x, y, alt),
        opk = (omega * math.pi/180, phi* math.pi/180, kappa * math.pi / 180),
    )  
    
    dem = rioxarray.open_rasterio(dem_path)#jeff.sel(x = slice(minlon,maxlon), y = slice(maxlat, minlat)).rio.reproject(crs)
    temp_dem_path = "{}/dem.tif".format(temp_dir)
    dem.rio.to_raster(temp_dem_path, driver = "GTIFF")
    ortho = oty.Ortho(temp_image_path, temp_dem_path, camera=cam_model, crs = crs)
    temp_ortho_path = "{}/ortho.tif".format(temp_dir)
    if os.path.isfile(temp_ortho_path):
        os.remove(temp_ortho_path)
    ortho.process(temp_ortho_path, driver = 'gtiff')
    ortho_data = rioxarray.open_rasterio(temp_ortho_path)
    
    
    return ortho_data






def write_cog_to_s3(data, s3_path, driver = 'COG', compress = 'JPEG'):
    local_outfile = '/tmp/temp_data.cog'
    data.rio.to_raster(local_outfile, driver = driver, compress = compress)
    command = "aws s3 cp {} {}".format(local_outfile, s3_path)
    print(command)
    os.system(command)


def get_dem_data(bbox, flight):
    
    
    with tempfile.TemporaryDirectory() as temp_dir:



        # STAC collection for Copernicus DEM 30 m (DGED, GeoTIFF/COG)
        stac_url = "https://stac.dataspace.copernicus.eu/v1"
        collection_id = "cop-dem-glo-30-dged-cog"

        # Copernicus Dataspace S3 credentials ⚠️
        # Either set them here manually OR via environment variables (CDSE_AWS_KEY / CDSE_AWS_SECRET)
        AWS_ACCESS_KEY = "CF209QUI1QUMWG99NS0B"
        AWS_SECRET_KEY = "QEUACb6Xl6UDsIVpbkV8uw3dTQIeJlz5la4e3GpJ"

        # ---------------------------
        # 2. Query STAC API
        # ---------------------------
        catalog = Client.open(stac_url)
        search = catalog.search(
            collections=[collection_id],
            bbox=bbox,
            limit=1000
        )
        #items = list(search.items())
        urls = [feature['assets']['data']['href'] for feature in search.get_all_items_as_dict()['features']]
        print(f"Found {len(urls)} tiles in collection {collection_id}")

        if len(urls) == 0:
            raise SystemExit("No DEM tiles found for this AOI.")

        # ---------------------------
        # 3. Connect to Copernicus Dataspace S3 (authenticated)
        # ---------------------------
        s3 = boto3.client(
            "s3",
            region_name="eu-central-1",
            endpoint_url="https://eodata.dataspace.copernicus.eu",
            aws_access_key_id=AWS_ACCESS_KEY,
            aws_secret_access_key=AWS_SECRET_KEY,
            config=Config(signature_version="s3v4")
        )
        bucket = "eodata"

        # ---------------------------
        # 4. Parallel download function
        # ---------------------------
        def download_tile(href):
            if href.startswith("s3://eodata/") and href.endswith(".tif"):
                key = href.replace("s3://eodata/", "")
                filename = os.path.join(temp_dir, os.path.basename(key))

                if os.path.exists(filename):
                    return f"Already exists: {filename}"

                try:
                    resp = s3.get_object(Bucket=bucket, Key=key, RequestPayer='requester')
                    with open(filename, "wb") as f:
                        for chunk in resp["Body"].iter_chunks(chunk_size=1024*1024):
                            f.write(chunk)
                    return f"✅ Downloaded: {filename}"
                except Exception as e:
                    print('bucket: {} key: {}'.format(bucket, key))
                    return f"❌ Failed: {key} ({e})"
            return None

        # ---------------------------
        # 5. Collect all URLs and run in parallel
        # ---------------------------
        # urls = [
        #     asset.href
        #     for item in items
        #     for asset_key, asset in item.assets.items()
        #     if asset.href.endswith(".tif")
        # ]

        print(f"Starting download of {len(urls)} DEM tiles...")

        # Detect available cores and subtract one (minimum 1)
        num_workers = max(1, os.cpu_count() - 1)
        print(f"Using {num_workers} parallel workers")

        with ThreadPoolExecutor(max_workers=num_workers) as executor:
            futures = [executor.submit(download_tile, u) for u in urls]
            for future in as_completed(futures):
                print(future.result())

        print("✅ All downloads finished.")

        dem_files = ["{}/{}".format(temp_dir, filename) for filename in os.listdir(temp_dir)]
        for dem_file in dem_files:
            outfile_prefix = dem_file.split('/')[-1]
            command = "aws s3 cp {} s3://dw-trackview/{}/dem/".format(dem_file, flight, outfile_prefix)
            print(command)
            os.system(command)

    

def s3_list_files(session, s3_path):
    """
    list files in an S3 bucket

    
    """

    m = re.match("s3://(?P<bucket>[^/]+)(|/)(?P<path>.*)", s3_path)
   
    bucket = m.group('bucket')
    path =   m.group('path').lstrip('/')
    
    
    s3_client = session.client('s3')
    objects = s3_client.list_objects_v2(Bucket=bucket, Prefix = path)
    if 'Contents' not in objects:
        return []
    key_list = [x['Key'] for x in objects['Contents']]

    return ["s3://{}/{}".format(bucket, key) for key in key_list] 

def s3_is_file(s3_path):

    m = re.match("s3://(?P<bucket>[^/]+)/(?P<object_name>.*)", s3_path)
    bucket = m.group('bucket')
    object_name = m.group('object_name')
    
    s3_client = boto3.client('s3')
    try:
        s3_client.head_object(Bucket=bucket, Key=object_name)
        return True
    except botocore.exceptions.ClientError as e:
        if e.response["Error"]["Code"] == "404":
            return False
        else:
            raise Exception('s3_is_file error')



def get_shapely_bbox_from_dataarray(da: xr.DataArray) -> Polygon:
    """
    Get the bounding box of valid (non-NaN) data in an xarray.DataArray
    as a Shapely rectangle (Polygon).

    Parameters
    ----------
    da : xr.DataArray
        2D DataArray with coordinates (y, x) or (lat, lon).

    Returns
    -------
    shapely.geometry.Polygon
        Bounding box polygon in the same coordinate reference system as the DataArray.
        Returns None if no valid data is found.
    """
    if not isinstance(da, xr.DataArray):
        raise TypeError("Input must be an xarray.DataArray.")

    if da.ndim != 2:
        raise ValueError("DataArray must be 2D (y, x).")

    # Identify valid (non-NaN) cells
    valid_mask = np.isfinite(da.values)
    if not np.any(valid_mask):
        return None  # No valid data

    # Get indices of valid data
    y_idx, x_idx = np.where(valid_mask)

    # Get coordinate values
    x_coords = da.coords[da.dims[1]].values
    y_coords = da.coords[da.dims[0]].values

    # Determine bounding coordinates
    min_x = x_coords[x_idx.min()]
    max_x = x_coords[x_idx.max()]
    min_y = y_coords[y_idx.max()]  # y may be descending
    max_y = y_coords[y_idx.min()]

    # Ensure correct ordering (in case coords are descending)
    min_x, max_x = sorted([min_x, max_x])
    min_y, max_y = sorted([min_y, max_y])

    # Create shapely box (minx, miny, maxx, maxy)
    return box(min_x, min_y, max_x, max_y)

def get_arguments(myfunction):
    return list(dict(inspect.signature(myfunction).parameters.items()).keys())


def tiles_covering_polygon(polygon, zoom):
    """
    Given a Shapely polygon in EPSG:4326 and a zoom level,
    return a GeoDataFrame with TMS z/x/y and tile polygons.
    """
    if polygon.is_empty:
        raise ValueError("Input polygon is empty.")
    if polygon.geom_type not in ["Polygon", "MultiPolygon"]:
        raise TypeError("Input geometry must be a Polygon or MultiPolygon.")

    # Get bounding box of the polygon
    minx, miny, maxx, maxy = polygon.bounds

    # Get all tiles intersecting the bounding box
    tiles = mercantile.tiles(minx, miny, maxx, maxy, zoom)

    records = []
    for t in tiles:
        # Get tile bounds in lon/lat
        bounds = mercantile.bounds(t)
        tile_poly = Polygon([
            (bounds.west, bounds.south),
            (bounds.east, bounds.south),
            (bounds.east, bounds.north),
            (bounds.west, bounds.north),
            (bounds.west, bounds.south)
        ])

        # Keep only tiles that intersect the polygon
        coverage = polygon.intersection(tile_poly).area/tile_poly.area
        if coverage > 0:
            records.append({
                "z": t.z,
                "x": t.x,
                "y": t.y,
                'coverage': coverage
            })

    # Create GeoDataFrame
    df = pd.DataFrame(records)
    return df.loc[df.coverage >= .99]


def align_with_tms(data):

    xmin = float(data.coords['x'].min())
    ymin = float(data.coords['y'].min())
    xmax = float(data.coords['x'].max())
    ymax = float(data.coords['y'].max())

    gsd_x = float((xmax - xmin)/data.shape[2])
    gsd_y = float((ymax - ymin)/data.shape[1])
    lon = (xmin + xmax)/2
    lat = (ymin + ymax)/2
    df_gsd = tile_gsds(lat, lon)
    z_index = int(((df_gsd.gsd_x<gsd_x) & (df_gsd.gsd_y < gsd_y)).argmax()) - 1
    zmax, gsd_x, gsd_y = df_gsd.iloc[z_index].values
    px_width = int(np.round((xmax - xmin)/gsd_x))
    px_height = int(np.round((ymax - ymin)/gsd_y))

    if data.shape[0] == 1:
         data_values = cv2.resize(data.values[0], (px_width, px_height))
         coords = {'y': np.linspace(ymax, ymin, data_values.shape[0]), 'x': np.linspace(xmin, xmax, data_values.shape[1])}
    else:
        data_values = cv2.resize(data.values.transpose(1,2,0), (px_width, px_height)).transpose(2,0,1)
        coords = {'band': range(data_values.shape[0]), 'y': np.linspace(ymax, ymin, data_values.shape[1]), 'x': np.linspace(xmin, xmax, data_values.shape[2])}
    
    data_out = xr.DataArray(data_values, coords = coords)
    data_out.rio.write_crs('epsg:4326', inplace = True)

    return data_out

def process_image(image_path, temp_dir = '/tmp', transparency_buffer = .05):
   
    image_index = int(re.findall("(?P<image_index>[0-9]+)", image_path)[-1])

    image_data = extract_exif_data(image_path)
    
    output_dir = "s3://dw-trackview"
    outfile_prefix = image_path.split('.')[0].split('/')[-1]

    flight_id = image_path.split('/')[-2]
    flight = flight_id.lower().replace('__', '_')

    
    
    with smart_open('s3://dw-trackview/{}/analysis_request.json'.format(flight)) as fp : 
        request_dict = json.load(fp)
    if 'wingtra' in request_dict['info']['drone_model'].lower():
        geotag_file = "s3://dw-trackview/{}/geotags.csv".format(flight)
        df_geotag = gpd.read_file(geotag_file).rename(columns = {'{} [degrees]'.format(key): key for key in ['omega', 'phi', 'kappa']})
        for key in ['omega', 'phi', 'kappa']:
            image_data[key] = float(df_geotag.loc[df_geotag['# image name'] == image_path.split('/')[-1], key].iloc[0])
    elif 'dji' in request_dict['info']['drone_model'].lower():
        result = extract_dji_orientation(image_path)
        image_data.update(result)
    elif 'superwake' in request_dict['info']['drone_model'].lower():
        result = extract_phaseone_orientation(image_path)
        image_data.update(result)   


    x, y, utm_zone, utm_code = utm.from_latlon(image_data['lat'], image_data['lon'])
    if utm_code == 'U':
        image_data['crs'] = 'epsg:326{}'.format(utm_zone)
    else:
         image_data['crs'] = 'epsg:327{}'.format(utm_zone)
    image_data['x'] = x
    image_data['y'] = y
 
   
    
    df_bounds = gpd.GeoDataFrame().set_geometry([box(x -50, y - 50, x + 50, y + 50)]).set_crs(image_data['crs']).to_crs('epsg:4326')
    dem_files = s3_list_files(boto3, 's3://dw-trackview/{}/dem'.format(flight))
    
    #if there are no dem files, get dem file for this location
    if len(dem_files) == 0:
        get_dem_data(list(df_bounds.geometry.iloc[0].bounds), flight)
    
    #get elevation from existing dem files on s3 if it covers this location
    dem_files = s3_list_files(boto3, 's3://dw-trackview/{}/dem'.format(flight))
    for dem_file in dem_files:
        dem_data = rioxarray.open_rasterio(dem_file)[0]
        polygon = get_shapely_bbox_from_dataarray(dem_data)
        if polygon.contains(Point(image_data['lon'], image_data['lat'])):
            image_data['elevation'] = float(dem_data.sel(x = image_data['lon'], y = image_data['lat'], method = 'nearest'))
            image_data['dem_path'] = dem_file
            break
    
    #if this location is not covered by existing dem_files, get dem file for this location
    if 'elevation' not in image_data :
        get_dem_data(list(df_bounds.geometry.iloc[0].bounds), flight)
    for dem_file in dem_files: #get elevation from the dem files
        dem_data = rioxarray.open_rasterio(dem_file)[0]
        polygon = get_shapely_bbox_from_dataarray(dem_data)
        if polygon.contains(Point(image_data['lon'], image_data['lat'])):
            image_data['elevation'] = float(dem_data.sel(x = image_data['lon'], y = image_data['lat'], method = 'nearest'))
            image_data['dem_path'] = dem_file
            break

   
    
    
    
    world_boundary = get_world_boundary(**{key:image_data[key] for key in get_arguments(get_world_boundary)})
    df_world_boundary = gpd.GeoDataFrame().set_geometry([world_boundary]).set_crs(image_data['crs']).to_crs('epsg:4326')
    world_boundary_4326 = df_world_boundary.geometry.iloc[0]
    image_data.update(dict(zip(['minlon', 'minlat', 'maxlon', 'maxlat'], world_boundary_4326.bounds)))


    
   
    data = orthorectify_image(**{key: image_data[key] for key in get_arguments(orthorectify_image)})
    data = data.rio.reproject('epsg:4326')
    
    
  

    
    boundary_geometry = box(*[image_data[key] for key in ['minlon', 'minlat', 'maxlon', 'maxlat']])
    transparent_geometry = boundary_geometry.difference(world_boundary_4326)

    max_dimension = max(image_data['maxlon'] - image_data['minlon'], image_data['maxlat'] - image_data['minlat'])
    transparent_geometry = transparent_geometry.buffer(transparency_buffer * max_dimension)

    df_mask = gpd.GeoDataFrame({'mask': [1, 0]}).set_geometry([world_boundary_4326, transparent_geometry]).set_crs('epsg:4326')
    mask = make_geocube(
        vector_data=df_mask,
        measurements=["mask"],
        resolution=(np.diff(data.coords['y']).mean(), np.diff(data.coords['x']).mean()),
    )['mask'].astype('uint8').sel(x = slice(image_data['minlon'], image_data['maxlon']), y = slice(image_data['maxlat'], image_data['minlat']))
    

    data_values = data.values
    mask_values = mask.values.reshape((1,) + mask.shape)
    if data_values.shape[1] < mask_values.shape[1]:
        mask_values = mask_values[:,:data_values.shape[1],:]
    elif data_values.shape[1] > mask_values.shape[1]:
        data_values = data_values[:, :mask_values.shape[1],:]

    if data_values.shape[2] < mask_values.shape[2]:
        mask_values = mask_values[:, :, :data_values.shape[2]]
    elif data_values.shape[2] > mask_values.shape[2]:
        data_values = data_values[:, :, :mask_values.shape[2]]
    

    xmin, ymin, xmax, ymax = [image_data[key] for key in ['minlon', 'minlat', 'maxlon', 'maxlat']]
    data_jpg = xr.DataArray(
        data_values * mask_values, 
        coords = {'band': [1,2,3], 'y': np.linspace(ymax,ymin,data_values.shape[1]), 'x': np.linspace(xmin,xmax, data_values.shape[2])}
    )
    data_jpg.rio.write_crs('epsg:4326', inplace = True)
    

    data_mask = xr.DataArray(
        255 * mask_values, 
        coords = {'band': [1], 'y': np.linspace(ymax,ymin,data_values.shape[1]), 'x': np.linspace(xmin,xmax, data_values.shape[2])}
    )
    data_mask.rio.write_crs('epsg:4326', inplace = True) 
    
    
    
    data_out = align_with_tms(data_jpg)
    data_mask_out = align_with_tms(data_mask)
    mask_polygon = convex_hull(data_mask_out)
    df_mask = tiles_covering_polygon(mask_polygon, zoom = 22)
    
    
    df_mask.loc[:, 'image_index'] = image_index
    
    s3_metadata_outfile = "s3://dw-trackview/{}/metadata/metadata_{}.parquet".format(flight, image_index)
    df_mask.to_parquet(s3_metadata_outfile)

    s3_rgb_outfile = "s3://dw-trackview/{}/raster/rgb_{}.cog".format(flight, image_index)
    write_cog_to_s3(data_out, s3_rgb_outfile)

    s3_mask_outfile = "s3://dw-trackview/{}/raster/mask_{}.cog".format(flight, image_index)
    write_cog_to_s3(data_mask_out, s3_mask_outfile, compress = 'PACKBITS')


    #process with ML algorithms if requested
    with smart_open('s3://dw-trackview/{}/analysis_request.json'.format(flight)) as fp: 
        request = json.load(fp)
    active_analyses = {'suspect_bad_ties': 'bad-tie-detector'}
    for key in active_analyses:
        if request['area_track'][key] == 'Y':
            event = {'flight': flight, 'image_index': image_index}
            print(event)
            lambda_client = boto3.client("lambda")
            
            # Invoke asynchronously using InvocationType='Event'
            response = lambda_client.invoke(
                FunctionName=active_analyses[key],
                InvocationType='Event',  # Asynchronous invocation
                Payload=json.dumps(event).encode('utf-8')
            )
            print(response)


    




  


def lambda_handler(event, context):
    
    print(event.keys())
    object_name = event['Records'][0]['s3']['object']['key']
    bucket_name = event['Records'][0]['s3']['bucket']['name']
    

    image_path = "s3://{}/{}".format(bucket_name, object_name)
    print("image path: {}".format(image_path))
    process_image(image_path)


if __name__ == "__main__":

 
    #bucket_name = 'ts-wkbch-file-uploads-bkt-fbef377'
    #object_name = "DEMO__20250815__DEMO_Cando_Rail_Demo_Flight__1d7d91e1/Cando_Rail_Demo_Flight_Flight_01_00005.JPG"
    bucket_name = "dw-jdiamond"
    object_name = "test_flight_1/DJI_8843890w340w389_001_V.JPG"
    event = json.loads(open('templates/s3_lambda_call_template.json').read().replace('bucket_name', bucket_name).replace('object_name', object_name))
    lambda_handler(event, context = None)
    
  


