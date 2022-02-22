import os
import subprocess
import requests
import time
import signal

def method():
    # step 1: start the process
    backend_path = '/home/miracle/config2spec/batfish/projects/backend/target/backend-bundle-0.36.0.jar'
    port = 8192
    ms_cmd = ['java', '-cp', '%s' % backend_path, 'org.batfish.backend.Backend', '%d' % port]
    ms_cmd = ['java', '-agentlib:jdwp=transport=dt_socket,server=y,suspend=n,address=127.0.0.1:5005', '-cp', '%s' % backend_path, 'org.batfish.backend.Backend', '%d' % port]
    process = subprocess.Popen(ms_cmd, preexec_fn=os.setsid)
    time.sleep(2)

    # step 2: init minesweeper
    base_url = '%s:%d' % ("http://localhost", port)

    data = 'BasePath:/tmp;ConfigPath:/home/miracle/config2spec/scenarios/bics/ospf/configs;ConfigFiles:Zurich.cfg,Ljubjana.cfg,Bucharest.cfg,Bratislava.cfg,Vienna.cfg,Kiev.cfg,Basel.cfg,Istanbul.cfg,London.cfg,Rotterdam.cfg,Madrid.cfg,Marseille.cfg,Frankfurt.cfg,Praha.cfg,Budapest.cfg,Warsaw.cfg,Lyon.cfg,Stockholm.cfg,Strasbourg.cfg,Geneva.cfg,Athens.cfg,Paris.cfg,Dublin.cfg,Lisbon.cfg,Milan.cfg,Barcelona.cfg,Brussels.cfg,Zagreb.cfg,Amsterdam.cfg,Vaduz.cfg,Roma.cfg,Luxembourg.cfg,Sofia.cfg'
    data = 'BasePath:/tmp;ConfigPath:/home/miracle/config2spec/scenarios/bics/bgp/configs;ConfigFiles:PeerAmsterdam_0.cfg,PeerBasel_3.cfg,Zurich.cfg,Ljubjana.cfg,PeerBrussels_5.cfg,PeerFrankfurt_7.cfg,Bucharest.cfg,PeerBrussels_4.cfg,Bratislava.cfg,Vienna.cfg,Kiev.cfg,Basel.cfg,Istanbul.cfg,London.cfg,PeerGeneva_8.cfg,PeerBarcelona_1.cfg,Rotterdam.cfg,Madrid.cfg,Marseille.cfg,Frankfurt.cfg,Praha.cfg,Budapest.cfg,Warsaw.cfg,Lyon.cfg,Stockholm.cfg,PeerIstanbul_10.cfg,PeerGeneva_9.cfg,PeerKiev_11.cfg,PeerStrasbourg_15.cfg,Strasbourg.cfg,Geneva.cfg,Athens.cfg,Paris.cfg,Dublin.cfg,Lisbon.cfg,Milan.cfg,Barcelona.cfg,Brussels.cfg,PeerMarseille_12.cfg,Zagreb.cfg,Amsterdam.cfg,Vaduz.cfg,Roma.cfg,PeerMilan_14.cfg,PeerBrussels_6.cfg,PeerMarseille_13.cfg,Luxembourg.cfg,PeerBasel_2.cfg,Sofia.cfg'
    data = 'BasePath:/tmp;ConfigPath:/home/miracle/config2spec/scenarios/test/configs;ConfigFiles:A,B'
    response = requests.post(
        url='{base_url}/{attribute}'.format(base_url=base_url, attribute='init_minesweeper'),
        data=data)
    response_content = response.content.decode('utf-8')

    # step 3: run query
    start = time.time()
    query = 'Type:reachability;IngressNodeRegex:^a$;FinalNodeRegex:b;FinalIfaceRegex:Loopback0;Negate:False;MaxFailures:0;Environment:;'
    response = requests.post(url='{base_url}/{attribute}'.format(base_url=base_url, attribute='run_query'), data=query)
    response_content = response.content.decode('utf-8')
    if 'Verified' == response_content.strip():
        print('Verified')
    else:
        print('No')
    total = time.time() - start
    print(total)

    start = time.time()
    query = 'Type:reachability;IngressNodeRegex:^a$;FinalNodeRegex:b;FinalIfaceRegex:Loopback0;Negate:False;MaxFailures:0;Environment:;'
    response = requests.post(url='{base_url}/{attribute}'.format(base_url=base_url, attribute='run_query'), data=query)
    response_content = response.content.decode('utf-8')
    if 'Verified' == response_content.strip():
        print('Verified')
    else:
        print('No')
    total = time.time() - start
    print(total)

if __name__ == '__main__':
    method()