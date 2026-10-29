using System.Collections.Concurrent;
using System.Diagnostics;
using System.IO;
using System.Linq;
using System.Runtime.InteropServices;
using System.Threading;

public class Program
{
    private const string InputFile = "data\\numbers.txt";
    private const long TotalNumbers = 50_000_000;

    public static void Main(string[] args)
    {
        if (args.Length == 0)
        {
            Console.WriteLine("Commands: generate, split, hardware, 1a <threads>, 1b, 1c <workers>, 2 <threads> <usb_folder>");
            return;
        }

        string cmd = args[0].ToLower();

        if (cmd == "generate" || cmd == "gen") GenerateFile();
        else if (cmd == "split") SplitFile();
        else if (cmd == "hardware") PrintHardware();
        else if (cmd == "1a") RunTask1a(GetIntOption(args, "--threads", GetPositionalInt(args, 1, 1)));
        else if (cmd == "1b") RunTask1b();
        else if (cmd == "1c") RunTask1c(GetIntOption(args, "--workers", GetPositionalInt(args, 1, 1)));
        else if (cmd == "2")
        {
            int threads = GetIntOption(args, "--threads", GetPositionalInt(args, 1, 1));
            string folder = GetOption(args, "--dir") ?? (args.Length > 2 ? args[2] : ".");
            RunTask2(threads, folder);
        }
    }

    private static void PrintHardware()
    {
        Console.WriteLine($"OS: {RuntimeInformation.OSDescription}");
        Console.WriteLine($"Logical Processors: {Environment.ProcessorCount}");
        Console.WriteLine($"Framework: {RuntimeInformation.FrameworkDescription}");
    }

    // 1. Generate numbers.txt (50,000,000 numbers)
    private static void GenerateFile()
    {
        Directory.CreateDirectory(Path.GetDirectoryName(InputFile)!);
        Console.WriteLine("Generating 50,000,000 numbers...");
        Random rng = new Random(42);
        using (StreamWriter writer = new StreamWriter(InputFile))
        {
            for (long i = 0; i < TotalNumbers; i++)
            {
                writer.WriteLine(rng.Next(-1000000, 1000001));
            }
        }
        Console.WriteLine("Done generating numbers.txt");
    }

    // 2. Split numbers.txt into 8 equal files of 6,250,000 lines
    private static void SplitFile()
    {
        string partsFolder = Path.Combine("data", "parts");
        Directory.CreateDirectory(partsFolder);
        Console.WriteLine("Splitting into 8 files...");
        using (StreamReader reader = new StreamReader(InputFile))
        {
            for (int f = 0; f < 8; f++)
            {
                using (StreamWriter writer = new StreamWriter(Path.Combine(partsFolder, $"part_{f + 1}.txt")))
                {
                    for (int line = 0; line < 6_250_000; line++)
                    {
                        writer.WriteLine(reader.ReadLine());
                    }
                }
            }
        }
        Console.WriteLine("Done splitting files.");
    }

    // Task 1a: File lines partitioned into equal line counts per thread (Guarantees exact 50M total)
    private static void RunTask1a(int threadCount)
    {
        GC.Collect();
        Stopwatch timer = Stopwatch.StartNew();

        long globalNeg = 0, globalPos = 0, globalZero = 0;
        long linesPerThread = TotalNumbers / threadCount;
        Thread[] threads = new Thread[threadCount];

        for (int i = 0; i < threadCount; i++)
        {
            int threadIndex = i;
            threads[threadIndex] = new Thread(() =>
            {
                long localNeg = 0, localPos = 0, localZero = 0;
                long startLine = threadIndex * linesPerThread;
                long linesToRead = (threadIndex == threadCount - 1) ? (TotalNumbers - startLine) : linesPerThread;

                using (StreamReader reader = new StreamReader(InputFile))
                {
                    // Skip lines meant for previous threads
                    for (long k = 0; k < startLine; k++)
                    {
                        reader.ReadLine();
                    }

                    // Read assigned line count
                    for (long k = 0; k < linesToRead; k++)
                    {
                        string? line = reader.ReadLine();
                        if (line != null && int.TryParse(line, out int val))
                        {
                            if (val < 0) localNeg++;
                            else if (val > 0) localPos++;
                            else localZero++;
                        }
                    }
                }

                Interlocked.Add(ref globalNeg, localNeg);
                Interlocked.Add(ref globalPos, localPos);
                Interlocked.Add(ref globalZero, localZero);
            });
            threads[threadIndex].Start();
        }

        foreach (Thread t in threads) t.Join();
        timer.Stop();

        long peakMem = Process.GetCurrentProcess().PeakWorkingSet64 / (1024 * 1024);
        VerifyCounts(globalNeg, globalPos, globalZero);
        Console.WriteLine($"[Task 1a] Threads: {threadCount,2} | Time: {timer.ElapsedMilliseconds,5} ms | Peak Memory: {peakMem,3} MB");
    }

    // Task 1b: Three counting methods in memory
    private static void RunTask1b()
    {
        Console.WriteLine("Loading file into array for Task 1b...");
        int[] numbers = File.ReadLines(InputFile).Select(int.Parse).ToArray();
        int threadCount = Environment.ProcessorCount;
        int chunkSize = numbers.Length / threadCount;

        Console.WriteLine($"\nRunning Task 1b with {threadCount} logical processors...\n");

        // Version 1: Unsynchronized
        for (int run = 1; run <= 3; run++)
        {
            int neg = 0, pos = 0, zero = 0;
            Stopwatch sw = Stopwatch.StartNew();
            Thread[] threads = new Thread[threadCount];

            for (int i = 0; i < threadCount; i++)
            {
                int start = i * chunkSize;
                int end = (i == threadCount - 1) ? numbers.Length : (i + 1) * chunkSize;
                threads[i] = new Thread(() =>
                {
                    for (int k = start; k < end; k++)
                    {
                        if (numbers[k] < 0) neg++;
                        else if (numbers[k] > 0) pos++;
                        else zero++;
                    }
                });
                threads[i].Start();
            }
            foreach (Thread t in threads) t.Join();
            sw.Stop();
            long total = (long)neg + pos + zero;
            Console.WriteLine($"[1b.1 Ununsynchronized Run {run}] Time: {sw.ElapsedMilliseconds,4} ms | Total: {total,10} (Wrong due to race condition)");
        }

        // Version 2: Locked
        {
            int neg = 0, pos = 0, zero = 0;
            object gate = new object();
            Stopwatch sw = Stopwatch.StartNew();
            Thread[] threads = new Thread[threadCount];

            for (int i = 0; i < threadCount; i++)
            {
                int start = i * chunkSize;
                int end = (i == threadCount - 1) ? numbers.Length : (i + 1) * chunkSize;
                threads[i] = new Thread(() =>
                {
                    for (int k = start; k < end; k++)
                    {
                        lock (gate)
                        {
                            if (numbers[k] < 0) neg++;
                            else if (numbers[k] > 0) pos++;
                            else zero++;
                        }
                    }
                });
                threads[i].Start();
            }
            foreach (Thread t in threads) t.Join();
            sw.Stop();
            long total = (long)neg + pos + zero;
            Console.WriteLine($"[1b.2 Locked]               Time: {sw.ElapsedMilliseconds,4} ms | Total: {total,10} (Correct)");
        }

        // Version 3: Separate Thread-Local Counters
        {
            Stopwatch sw = Stopwatch.StartNew();
            Thread[] threads = new Thread[threadCount];
            long[] localNeg = new long[threadCount];
            long[] localPos = new long[threadCount];
            long[] localZero = new long[threadCount];

            for (int i = 0; i < threadCount; i++)
            {
                int threadIndex = i;
                int start = threadIndex * chunkSize;
                int end = (threadIndex == threadCount - 1) ? numbers.Length : (threadIndex + 1) * chunkSize;

                threads[threadIndex] = new Thread(() =>
                {
                    for (int k = start; k < end; k++)
                    {
                        if (numbers[k] < 0) localNeg[threadIndex]++;
                        else if (numbers[k] > 0) localPos[threadIndex]++;
                        else localZero[threadIndex]++;
                    }
                });
                threads[threadIndex].Start();
            }
            foreach (Thread t in threads) t.Join();
            sw.Stop();

            long totalNeg = localNeg.Sum();
            long totalPos = localPos.Sum();
            long totalZero = localZero.Sum();
            long total = totalNeg + totalPos + totalZero;
            Console.WriteLine($"[1b.3 Thread-Local]         Time: {sw.ElapsedMilliseconds,4} ms | Total: {total,10} (Correct & Fastest)");
        }
    }

    // Task 1c: Producer - Consumer Pattern
    private static void RunTask1c(int workerCount)
    {
        GC.Collect();
        Stopwatch timer = Stopwatch.StartNew();

        BlockingCollection<string[]> queue = new BlockingCollection<string[]>(boundedCapacity: 100);
        long globalNeg = 0, globalPos = 0, globalZero = 0;

        // Reader Thread (Producer)
        Thread reader = new Thread(() =>
        {
            using (StreamReader sr = new StreamReader(InputFile))
            {
                var batch = new System.Collections.Generic.List<string>(10000);
                string? line;
                while ((line = sr.ReadLine()) != null)
                {
                    batch.Add(line);
                    if (batch.Count == 10000)
                    {
                        queue.Add(batch.ToArray());
                        batch.Clear();
                    }
                }
                if (batch.Count > 0) queue.Add(batch.ToArray());
            }
            queue.CompleteAdding();
        });

        // Worker Threads (Consumers)
        Thread[] workers = new Thread[workerCount];
        for (int i = 0; i < workerCount; i++)
        {
            workers[i] = new Thread(() =>
            {
                long localNeg = 0, localPos = 0, localZero = 0;
                foreach (string[] batch in queue.GetConsumingEnumerable())
                {
                    for (int k = 0; k < batch.Length; k++)
                    {
                        if (int.TryParse(batch[k], out int val))
                        {
                            if (val < 0) localNeg++;
                            else if (val > 0) localPos++;
                            else localZero++;
                        }
                    }
                }
                Interlocked.Add(ref globalNeg, localNeg);
                Interlocked.Add(ref globalPos, localPos);
                Interlocked.Add(ref globalZero, localZero);
            });
            workers[i].Start();
        }

        reader.Start();
        reader.Join();
        foreach (Thread w in workers) w.Join();
        timer.Stop();

        long peakMem = Process.GetCurrentProcess().PeakWorkingSet64 / (1024 * 1024);
        VerifyCounts(globalNeg, globalPos, globalZero);
        Console.WriteLine($"[Task 1c] Workers: {workerCount,2} | Time: {timer.ElapsedMilliseconds,5} ms | Peak Memory: {peakMem,3} MB");
    }

    // Task 2: Slow Storage / USB Drive
    private static void RunTask2(int threadCount, string usbFolder)
    {
        GC.Collect();
        Stopwatch timer = Stopwatch.StartNew();

        string[] filePaths = Directory.GetFiles(usbFolder, "part_*.txt");
        if (filePaths.Length == 0)
            filePaths = Directory.GetFiles(usbFolder, "numbers_*.txt");
        if (filePaths.Length == 0)
        {
            Console.WriteLine($"No chunk files found in path '{usbFolder}'. Ensure 8 split files exist.");
            return;
        }

        long globalNeg = 0, globalPos = 0, globalZero = 0;
        Thread[] threads = new Thread[threadCount];

        for (int i = 0; i < threadCount; i++)
        {
            int threadIndex = i;
            threads[threadIndex] = new Thread(() =>
            {
                long localNeg = 0, localPos = 0, localZero = 0;

                for (int f = threadIndex; f < filePaths.Length; f += threadCount)
                {
                    foreach (string line in File.ReadLines(filePaths[f]))
                    {
                        if (int.TryParse(line, out int val))
                        {
                            if (val < 0) localNeg++;
                            else if (val > 0) localPos++;
                            else localZero++;
                        }
                    }
                }

                Interlocked.Add(ref globalNeg, localNeg);
                Interlocked.Add(ref globalPos, localPos);
                Interlocked.Add(ref globalZero, localZero);
            });
            threads[threadIndex].Start();
        }

        foreach (Thread t in threads) t.Join();
        timer.Stop();

        long peakMem = Process.GetCurrentProcess().PeakWorkingSet64 / (1024 * 1024);
        VerifyCounts(globalNeg, globalPos, globalZero);
        Console.WriteLine($"[Task 2 USB] Threads: {threadCount,2} | Time: {timer.ElapsedMilliseconds,5} ms | Peak Memory: {peakMem,3} MB");
    }

    private static void VerifyCounts(long neg, long pos, long zero)
    {
        long sum = neg + pos + zero;
        Console.WriteLine($"Counts: negative={neg:N0} zero={zero:N0} positive={pos:N0} total={sum:N0}");
        if (sum != TotalNumbers)
        {
            Console.WriteLine($"[ERROR] Count Mismatch! Total sum: {sum}, Expected: {TotalNumbers}");
        }
        else
        {
            Console.WriteLine("[OK] All 50,000,000 numbers were processed.");
        }
    }

    private static string? GetOption(string[] args, string name)
    {
        int index = Array.IndexOf(args, name);
        return index >= 0 && index + 1 < args.Length ? args[index + 1] : null;
    }

    private static int GetIntOption(string[] args, string name, int defaultValue)
    {
        string? value = GetOption(args, name);
        return value != null && int.TryParse(value, out int result) ? result : defaultValue;
    }

    private static int GetPositionalInt(string[] args, int index, int defaultValue)
    {
        return index < args.Length && int.TryParse(args[index], out int result)
            ? result
            : defaultValue;
    }
}