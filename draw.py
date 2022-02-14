import os
import matplotlib.pyplot as plt


def get_data(path):
    datas = []
    with open(path, 'r') as reader:
        lines = reader.readlines()
        for line in lines:
            if 'total' not in line:
                entry = line.strip().split(' ')
                datas.append(int(float(entry[1]) * 1000))
    return datas

if __name__ == '__main__':
    path = '/home/miracle/config2spec/result/bics_bgp'
    path1 = os.path.join(path, 'incremental_verification_result.txt')
    path2 = os.path.join(path, 'full_verification_result.txt')
    y1 = get_data(path1)
    y2 = get_data(path2)
    x = list(range(1, len(y1)+1))
    plt.plot(x, y1, color='r', label='pp')
    plt.plot(x, y2, color='g', label='full')
    plt.ylabel('time(ms)')
    plt.legend(loc = 'best')
    plt.title('bics ospf')
    plt.show()
    print()
