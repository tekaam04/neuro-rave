import matplotlib.pyplot as plt

def plot_fft(sp):
    plt.plot(sp.real)
    plt.hold(False)
    plt.show()