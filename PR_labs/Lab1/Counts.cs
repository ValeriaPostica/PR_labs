public struct Counts(long negative = 0, long zero = 0, long positive = 0)
{
    public long Negative = negative;
    public long Zero = zero;
    public long Positive = positive;
    public readonly long Total => Negative + Zero + Positive;

    public void Add(int value)
    {
        if (value < 0) Negative++;
        else if (value > 0) Positive++;
        else Zero++;
    }

    public void Add(Counts other)
    {
        Negative += other.Negative;
        Zero += other.Zero;
        Positive += other.Positive;
    }

    public override readonly string ToString() =>
        $"negative={Negative:N0} zero={Zero:N0} positive={Positive:N0} total={Total:N0}";

    public static bool operator ==(Counts left, Counts right) =>
        left.Negative == right.Negative &&
        left.Zero == right.Zero &&
        left.Positive == right.Positive;

    public static bool operator !=(Counts left, Counts right) => !(left == right);
    public override readonly bool Equals(object? obj) => obj is Counts other && this == other;
    public override readonly int GetHashCode() => HashCode.Combine(Negative, Zero, Positive);
}
