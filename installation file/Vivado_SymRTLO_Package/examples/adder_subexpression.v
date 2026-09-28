module adder_subexpression (clk, a, b, c, d, out1, out2);
  input clk;
  input [7:0] a;
  input [7:0] b;
  input [7:0] c;
  input [7:0] d;
  output [7:0] out1;
  output [7:0] out2;
  
  assign out1 = (a + b) * c;
  assign out2 = (a + b) + d + 0;
endmodule
