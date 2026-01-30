import math

# 输入参数
D = 110.0  # 对角线视场角（度）
a = 16.0
b = 9.0
r = a / b  # 宽高比 16/9 ≈ 1.7778

# 转换为弧度
D_half_rad = math.radians(D / 2)
k = math.tan(D_half_rad)

# 计算 x = tan(V/2)
x = k / math.sqrt(r**2 + 1)

# 计算垂直视场角 V
V_half_rad = math.atan(x)
V = math.degrees(V_half_rad) * 2

# 计算水平视场角 H
H_half_rad = math.atan(r * x)
H = math.degrees(H_half_rad) * 2

print(f"对角线视场角: {D:.2f}°")
print(f"宽高比: {a:.0f}:{b:.0f} ({r:.4f})")
print(f"水平视场角 H: {H:.2f}°")
print(f"垂直视场角 V: {V:.2f}°")
print(f"验证: H/V = {H/V:.4f} ≈ {r:.4f}")