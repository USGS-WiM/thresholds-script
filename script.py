import json
import base64
import requests
import urllib
import sys
sys.path.insert(1, 'C:/Users/lprivette/Documents/settings')
import thresholds_secrets
import boto3
from botocore.exceptions import NoCredentialsError

# URLS
AQUARIUS_URL  = 'https://tsqa.nwis.usgs.gov/AQUARIUS/'
ahps_url = "https://hads.ncep.noaa.gov/USGS/ALL_USGS-HADS_SITES.txt"
rp_endpoint = 'Provisioning/v1/locations/'
location_description_endpoint = 'GetLocationDescriptionList'
location_data_endpoint = 'Publish/v2/GetLocationData?LocationIdentifier='
time_series_description_list_endpoint = 'Publish/v2/GetTimeSeriesDescriptionList?LocationIdentifier='

# VARIABLES
s3Client = boto3.client('s3', aws_access_key_id=thresholds_secrets.aws_access_key, aws_secret_access_key=thresholds_secrets.aws_secret_key)

locations = ["Georgia", "Virginia", "California", "MA-RI", "Colorado", "Nebraska", "North Carolina", "Pennsylvania", "South Carolina", "Florida", "Puerto Rico", "Kentucky", "North Dakota", "Pacific Islands", "Arizona", "Minnesota", "Wisconsin"]

uniqueIDs = [] 
referencePoints = []
output = []
nws_usgs_crosswalk = []

# FUNCTIONS
# deletes bucket contents
def delete_bucket_contents():
    s3Resource = boto3.resource('s3', aws_access_key_id=thresholds_secrets.aws_access_key, aws_secret_access_key=thresholds_secrets.aws_secret_key)
    obj = s3Resource.Object('thresholds.wim.usgs.gov','output.json').delete()
 
# uploads file to aws
def upload_to_aws(local_file, bucket, s3_file):
    try:
        s3Client.upload_file(local_file, bucket, s3_file, ExtraArgs={'ContentType': 'application/json'})
        print("Upload Successful")
        return True
    except FileNotFoundError:
        print("The file was not found")
        return False
    except NoCredentialsError:
        print("Credentials not available")
        return False

# queries resources to build json output
def build_output_json():
    # getting NWS AHPS locations for crosswalk
    textfile = urllib.request.urlopen(ahps_url)

    # count used to skip txt table headers
    count = 0
    for line in textfile:
        if count < 4:
            count = count + 1
            continue
        decoded_line = line.decode("utf-8")
        nws_id = decoded_line[0:5]
        usgs_id = decoded_line[6:21]
        usgs_id_nospaces = usgs_id.replace(" ", "")
        obj = ({'usgs_id': usgs_id_nospaces, 'nws_id': nws_id})
        nws_usgs_crosswalk.append(obj)

    # Getting each state's surface water locations
    for state in locations:
        r = requests.get(AQUARIUS_URL + 'Publish/v2/GetLocationDescriptionList?LocationFolder=All%20Locations.' + state + '.SW', auth=(thresholds_secrets.aq_username, thresholds_secrets.aq_password), timeout=10)
        # loading response into json
        data = json.loads(r.text);

        # stepping into and defining the locationDescriptions
        site_identifiers = data['LocationDescriptions']

        for item in site_identifiers:
        # removing duplicates
            if item['Identifier'] not in uniqueIDs:
                # Putting UniqueIds into an array
                uniqueIDs.append(item['Identifier'])

    # For each locationId get all thresholds
    for identifier in uniqueIDs:
        thresholds = []
        rpCandidate = []
        combinedIdentCand = {}
        # getting RPs
        getRPs = requests.get(AQUARIUS_URL + location_data_endpoint + identifier , auth=(thresholds_secrets.aq_username, thresholds_secrets.aq_password))
        rpResult = getRPs.json()
        try: 
            lng = len(rpResult['ReferencePoints'])
        except:
            print("An exception occurred", rpResult)
        # if location has refrence points go and get the thresholds
        if lng > 0:
            # for each reference point need to get the associated thresholds
            for rp in rpResult['ReferencePoints']:
                # getting Thresholds
                getThresholds = requests.get(AQUARIUS_URL + time_series_description_list_endpoint + identifier , auth=(thresholds_secrets.aq_username, thresholds_secrets.aq_password), timeout=10)
                thresholdResult = getThresholds.json()
                items = thresholdResult['TimeSeriesDescriptions']
                # for each description entry there is a thresholds array
                for x in items:
                    length = len(x['Thresholds'])
                    if length > 0:
                        # if the parameter is gage height, add it to the thresholds
                        if x['Parameter'] == "Gage height":
                            # Checking Publish to make sure this site is complete
                            if x['Publish'] == True:
                                thresholds.append(x)
                candlng = len(thresholds)
                if candlng > 0:
                    # checking if it has an nws id
                    nwsId = ""
                    for id in nws_usgs_crosswalk:
                        if id['usgs_id'] == identifier:
                            nwsId = id['nws_id']
                            
                    try:
                        buildObject = ({'LocationIdentifier': x['LocationIdentifier'], 'SiteName': rpResult['LocationName'], 'Name': rp['Name'], 'Latitude': rp['Latitude'], 'Longitude': rp['Longitude'], 'Elevation': rp['ReferencePointPeriods'][0]['Elevation'], 'Unit': rp['ReferencePointPeriods'][0]['Unit'], 'nws_id': nwsId})
                    except:
                        print("An exception occurred", rp)
                    
                    rpCandidate.append(buildObject)
                if len(thresholds) != 0:
                    output.append(rpCandidate[0])
                    rpCandidate.clear()

    #writing json to txt file             
    with open('data.json', 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=4)
        
    # delete old files in s3
    delete_bucket_contents()
        
    # uploading to s3
    uploaded = upload_to_aws('data.json', 'thresholds.wim.usgs.gov', 'output.json')

# building the json object and then deploying to s3 bucket
build_output_json()

