// 文件作用：纯 SVG 折线图。零依赖，适合训练 metric 实时可视化。
//
// 用法：
//   <SimpleLineChart
//     title="reward_mean per cycle"
//     data={[{x: 0, y: 0.3}, {x: 1, y: 0.5}, ...]}
//     yLabel="reward" yMin={-1} yMax={1}
//     width={520} height={180} stroke="#4a6b88"
//   />

import { useMemo } from "react";

export interface Point {
  x: number;
  y: number;
}

interface Props {
  title: string;
  data: Point[];
  width?: number;
  height?: number;
  stroke?: string;
  fill?: string;        // 区域填充色（半透明），传空字符串则不画
  yLabel?: string;
  yMin?: number;
  yMax?: number;
  refLine?: number;     // 在 y=refLine 画水平参考线（如 y=0）
}

const PAD_L = 36;
const PAD_R = 12;
const PAD_T = 18;
const PAD_B = 28;

export function SimpleLineChart({
  title,
  data,
  width = 520,
  height = 200,
  stroke = "#4a6b88",
  fill = "rgba(74,107,136,0.12)",
  yLabel = "",
  yMin,
  yMax,
  refLine,
}: Props) {
  const { path, areaPath, xs, yScale, xScale, autoYMin, autoYMax } = useMemo(() => {
    const innerW = width - PAD_L - PAD_R;
    const innerH = height - PAD_T - PAD_B;
    if (data.length === 0) {
      return {
        path: "", areaPath: "", xs: [],
        yScale: (y: number) => y, xScale: (x: number) => x,
        autoYMin: 0, autoYMax: 1,
      };
    }
    const xsArr = data.map((d) => d.x);
    const ysArr = data.map((d) => d.y);
    const xMin = Math.min(...xsArr);
    const xMax = Math.max(...xsArr);
    const dyMin = yMin ?? Math.min(...ysArr, refLine ?? Infinity);
    const dyMax = yMax ?? Math.max(...ysArr, refLine ?? -Infinity);
    const ySpan = Math.max(1e-6, dyMax - dyMin);
    const xSpan = Math.max(1, xMax - xMin);
    const yScale = (y: number) => PAD_T + innerH - ((y - dyMin) / ySpan) * innerH;
    const xScale = (x: number) => PAD_L + ((x - xMin) / xSpan) * innerW;
    const pts = data.map((d) => `${xScale(d.x).toFixed(1)},${yScale(d.y).toFixed(1)}`);
    const path = "M" + pts.join(" L");
    const baseY = yScale(Math.max(dyMin, 0));
    const areaPath = data.length > 1
      ? `M${xScale(data[0].x).toFixed(1)},${baseY} L${pts.join(" L")} L${xScale(data[data.length - 1].x).toFixed(1)},${baseY} Z`
      : "";
    return { path, areaPath, xs: xsArr, yScale, xScale, autoYMin: dyMin, autoYMax: dyMax };
  }, [data, width, height, yMin, yMax, refLine]);

  const lastPt = data.length > 0 ? data[data.length - 1] : null;

  return (
    <div className="chart-card">
      <div className="chart-title">
        <span>{title}</span>
        {lastPt && (
          <span className="chart-last">
            最新: x={lastPt.x} y={lastPt.y.toFixed(3)}
          </span>
        )}
      </div>
      <svg width={width} height={height} className="chart-svg">
        {/* y 轴线 + label */}
        <line x1={PAD_L} y1={PAD_T} x2={PAD_L} y2={height - PAD_B}
              stroke="#d8cfb8" strokeWidth={1} />
        <line x1={PAD_L} y1={height - PAD_B} x2={width - PAD_R} y2={height - PAD_B}
              stroke="#d8cfb8" strokeWidth={1} />
        {/* y 上/下界刻度 */}
        <text x={PAD_L - 6} y={PAD_T + 4} textAnchor="end" className="chart-tick">
          {autoYMax.toFixed(2)}
        </text>
        <text x={PAD_L - 6} y={height - PAD_B} textAnchor="end" className="chart-tick">
          {autoYMin.toFixed(2)}
        </text>
        {/* x 上/下界 */}
        {data.length > 0 && (
          <>
            <text x={PAD_L} y={height - PAD_B + 14} className="chart-tick">
              {xs[0]}
            </text>
            <text x={width - PAD_R} y={height - PAD_B + 14}
                  textAnchor="end" className="chart-tick">
              {xs[xs.length - 1]}
            </text>
          </>
        )}
        {/* y 轴标签 */}
        {yLabel && (
          <text x={6} y={PAD_T + 10} className="chart-ylabel">{yLabel}</text>
        )}
        {/* 参考线 */}
        {refLine !== undefined && data.length > 0 && (
          <line
            x1={PAD_L} x2={width - PAD_R}
            y1={yScale(refLine)} y2={yScale(refLine)}
            stroke="#aaa" strokeDasharray="3 3" strokeWidth={1}
          />
        )}
        {/* 区域填充 */}
        {fill && areaPath && <path d={areaPath} fill={fill} stroke="none" />}
        {/* 折线 */}
        {path && <path d={path} stroke={stroke} strokeWidth={1.8} fill="none" />}
        {/* 数据点 */}
        {data.map((d, i) => (
          <circle
            key={i}
            cx={xScale(d.x)} cy={yScale(d.y)}
            r={2.5} fill={stroke}
          />
        ))}
        {/* 数据少时显示提示 */}
        {data.length === 0 && (
          <text x={width / 2} y={height / 2} textAnchor="middle" className="chart-empty">
            暂无数据
          </text>
        )}
      </svg>
    </div>
  );
}
