import resource

from weasyprint import HTML


def peak_memory_mib() -> float:
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return rss / 1024 / 1024


for i in range(1000):
    HTML(string='<h1>Hello</h1>').write_pdf()

    if i in {0, 9, 99, 499, 999}:
        print(f'{i + 1} PDFs: {peak_memory_mib():.1f} MiB peak RSS')
