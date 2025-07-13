from volcenginesdktransitrouter import TransitRouterBandwidthPackageForDescribeTransitRouterBandwidthPackagesOutput
import volcenginesdkcore

import volcenginesdkautoscaling
from __future__ import print_function
import volcenginesdkecs
import volcenginesdkcore
from pprint import pprint
from volcenginesdkcore.rest import ApiException

var = TransitRouterBandwidthPackageForDescribeTransitRouterBandwidthPackagesOutput()

configuration = volcenginesdkcore.Configuration()
configuration.client_side_validation = True  # 客户端是否进行参数校验
configuration.schema = "http"  # https or http
configuration.debug = False  # 是否开启调试
configuration.logger_file = "sdk.log"
configuration = volcenginesdkcore.Configuration()
configuration.host = 'ecs.cn-beijing-autodriving.volcengineapi.com'

volcenginesdkcore.Configuration.set_default(configuration)

def get_client(ak, sk, region):
    # 包含默认属性
    configuration = volcenginesdkcore.Configuration()
    configuration.ak = ak
    configuration.sk = sk
    configuration.region = region
    client = volcenginesdkautoscaling.AUTOSCALINGApi(volcenginesdkcore.ApiClient(configuration))
    return client

if __name__ == '__main__':
    configuration = volcenginesdkcore.Configuration()
    configuration.ak = "Your AK"
    configuration.sk = "Your SK"
    configuration.region = "cn-beijing"
    configuration.client_side_validation = True
    # set default configuration
    volcenginesdkcore.Configuration.set_default(configuration)

    # use global default configuration
    api_instance = volcenginesdkecs.ECSApi()
    # use custom configuration
    # api_instance = volcenginesdkecs.ECSApi(volcenginesdkcore.ApiClient(configuration))

    try:
        resp = api_instance.run_instances(
            volcenginesdkecs.RunInstancesRequest(
                instance_name="insname",
                instance_type="ecs.g1.large",
                zone_id="cn-beijing-a",
                network_interfaces=[volcenginesdkecs.NetworkInterfaceForRunInstancesInput(
                    subnet_id="subnet-2d68bh73d858ozfekrm8fj",
                    security_group_ids=["sg-2b3dq7v0ha0w2dx0eg0nhljv"],
                )],
                image_id="image-ybvz29l3da4ox5h0m9",
                volumes=[volcenginesdkecs.VolumeForRunInstancesInput(
                    volume_type="ESSD",
                    size=40,
                )],
                key_pair_name="vtable",
                instance_charge_type="PostPaid"
            ))
        pprint(resp)
    except ApiException as e:
        print("Exception when calling ECSApi->run_instances: %s\n" % e)
