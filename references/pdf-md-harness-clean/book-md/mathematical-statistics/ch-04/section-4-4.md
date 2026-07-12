# 4.4 다변량 정규분포

> OCR engine: macOS Vision (`ko-KR,en-US`)
> Original PDF pages: 173-194

<!-- page 173 -->

다변량 정규분포

통계 조사에서는 조사 대상의 한 가지 특성보다는 서로 연관을 가지고 있는 여러 개의 특성을 동시에 관측하고 이들에 기초하여 추론을 하게 된다. 이러한 다차원 자료 를 이용하는 경우에 추론을 위한 기본 모형으로서는 일차원 정규분포를 다차원으로 확 장한 다변량 정규분포($뮬 I5AMi, multivariate normal distribution) 모형이 흔히 이용된다. 정리 4.4.1 표준정규분포 N(0, 1)을 따르고 서로 독립인 확률변수 Z1, Z2, •·, 2,과 상수의 행렬과 벡터 A=(ailsisn k=(A;kkm) 에 대하여 1≤js n Xi= 01Z,++anznth

## X,

= 0n1Z1++amZnt An 즉, X=AZ+MX=(X1,…,X,), Z=(Z,,,Z,) 이라고 할 때, 다음이 성립한다. (a) 행렬 A가 정칙행렬(TEMAT 3l, nonsingular matrix)이면 X= AZ+A의 확률밀 도함수는 paljx (2)=(det(275)-12exp(-(a-r)너'(a-K)/2}, 2ER" (5= A4) (6) X= AZ+A의 적률생성함수는 mgtx(t)=exp(We+글퍼,EP [증명] 정리 3.6.1>로부터 Z= (Z1; 22),2,)'의 확률밀도함수와 적률생성함수 는 각각 pdfz(2)= (2T) = (2) !!

## , 2ER"

## , SER"

(a) X=2(2)= AZ+A라고 할 때 A가 정칙행렬이면 함수 w는 R"에서 R”으 로의 일대일 함수로서 정리 4.1.1>의 조건을 만족시키고, 그 역수

<!-- page 174 -->

u'(z)=A-|(z-K)의 야코비안 행렬식은 J-=det(4-1)=(det(A) 1 로 주어진다. 따라서 paljx (a)=pdfz(u(a)4(2) -(2m) 0/Pexp-글(-(a-r) 11(8-r) (der(4) 1 여기에서 L= AA'라고 하면 det (272)= (27) (det(A))? 이므로 pals (r)=(ae(372) 1Pesp12(-5)516-0) (6) mgfx(t)=Elexplt(AZ+x)h]=mgjz(At)exp(tw) mgtx(1)=exp(it+½(8)(8)=ex02+½62) <정리 4.4.1>에서 구한 X의 분포를 다변량 정규분포라고 하며 기호로는 X~N,, (w, 2) 또는 변수의 개수를 생략하고 간략히 X ~ N (w, 2)로 나타낸다. 특히 (a)의 경우와 같이 2가 역행렬을 갖는 정칙행렬인 경우에는 X의 분포를 정칙 다변량 정규분포(TE 상을 ItAt, nonsingular multivariate normal distribution)라고 한다. 정리 4.4.2 (a) X~N(W,2)이면 E(X)= K, Var(X)= 2 (6) 분산행렬 I에 대하여 AA'= 5, A= A'인 행렬 A를 E1/2이라고 하면59) x~N,(5) exE2z+AZ~N(O.) [증명] (a) 2장 5절에서 밝혔듯이 다차원 확률변수의 평균벡터와 분산행렬은 누

## 율생성함수를 편미분하여 구할 수 있다. 그런데 N (K, 2)의 누율생성함수는

C(t)= 10g mgix (t)= wlt+들:5

59) <정리 2.5.4>로부터 분산행렬 5는 음이 아닌 정부호의 행렬이고, 부록 II에서 이러한

행렬에 대하여 212512= 2인 대칭행렬 51/2이 존재하는 것을 밝히고 있다. 180 4장 표본분포

<!-- page 175 -->

따라서 이 누율생성함수를 편미분하여 평균벡터와 분산행렬을 구하면 E(x)=C(o)=A Var(X)=C(O) = 20 (6) <정리 4.4.1>의 (6)에서와 같은 방법으로 271/251/2 = 5인 대칭행렬 21/2에 대하여 mssiz+nt)=exp (Wt+글다, tER

## 임을 밝힐 수 있으므로 X ~ N, (, 5)이다.

다변량 정규분포의 정의: Z~N, (0,1) 6Z=(7,2,), Z~N(0,1) (i=1,,n) x~N,(5) (1001 x= AZ+AZ~N(OD), A1=5 = (2) X= 5/2Z+4, 2~N,(0,1), 512512= 5, 512= (212)1 6(3) mgh(t)=exp wt+ , tERn = (4) (분산행렬 2가 정칙행렬인 경우) pdfx (a)=(det(275)-1Pexp 예 4.4.1 이변량 정규분포 100102 0일 또는 N(41) A2;0i, 03,p) 분산행렬 대하여 det(2)= 0303(1-p2)이므로, 01> 0, 02≥ 0, -1<pC 1이면 103 - 00102 0203(1-p2) 1-p0102 03 따라서 01> 0, 02> 0, - 1≤p< 1이면 확률밀도함수가 다음과 같이 주어진다. f(a1;22)=

- h0

270192V1-p2 1-p2

60) 정의 (1)에서 A가 nxn 정방행렬이어야만 하는 것은 아니며 AA'= 2인 nX m 행렬

이어도 무방하다.

<!-- page 176 -->

한편 01> 0, 02≥ 0, p=±1인 경우에는 분산행렬의 역행렬이 존재하지 않고 <정리 2.2.3>으로부터 다음과 같이 두 변수 사이에 선형 관계가 성립하는 것을 알 수 있다. P=16P X2- 12 =

## XI-씨

"2 =1 p=- 16P

## X 2- 12

X.-m 정리 4.4.3 다변량 정규분포의 성질 (a) X~N (4, 2)이면 상수의 행렬과 벡터 4와 6에 대하여

## AX+6~N(Au+b,ACA))

일 때, Cor(X1, X2)= 212= 0이면 X, 과 X2는 서로 독립이다. (c) X~N(W, 2)이고 A, B가 상수의 행렬일 때, Cor(AX, BX)= ALB'= 0

## 이면 AX와 BX는 서로 독립이다.

[증명] (a) 다변량 정규분포의 정의 (2)로부터 x'/2+EZN(01), 51252= 5, 2222=(212) AX+62(15/2)2+(Ax+6), 2~N(0.1), (4512)(1212)= 184' 따라서 다변량 정규분포의 정의 (1)로부터

## AX+6~N(Au+6,42A)

## (6) 다변량 정규분포의 정의 (3)으로부터 X, 과 X2의 결합적률생성함수는

ngJx1X2 여기에서 Cor(X1;X2)= 212= 0이면 221=(512)' = 0이므로 결합적률 생성함수가 로서 t, 만의 함수와 t2만의 함수의 곱으로 주어진다. 따라서 X,과 X2는 서 로 독립이다. (c) (a)로부터 182 4장 표본분포

<!-- page 177 -->

(a)-(6)×~ (60)

## AZA' ALB'

## BEA' BIB!

따라서 (b)로부터 Cor(AX, BX)= AIB'= 0이면 AX와 BX는 서로 독 립이다. 예 4.4.2 이변량 정규분포에서의 독립성 <정리 2.4.4>와 <예 2.4.32으로부터 두 확률변수 X,과 X2가 서로 독립이면 Cor(X1;22)= 0 이지만 그 역이 항상 성립하는 것은 아니라는 것을 알고 있다. 그러나 이변량 정 규분포를 따르는 (X1,X 2)'의 경우에는 Cor(X1,X2)= 0이면 X, 과 X2가 서로 독립이다. 정리 4.4.4 다변량 정규분포의 주변분포와 조건부분포 (a) (주변분포) X~N(1,2i1) (b) (조건부분포) 이고 분산행렬이 정칙행렬이면 X2x1=1,~N(2t52157(81-1),222-52552) (종명) (a) 2,= 1.02: )이므로, 정리 44.2의 (3)로부터 : X1~NW,Mir) (b) 이 경우의 분산행렬과 같이 부분행렬로 분할되어 있는 정칙행렬에 대하여 let 2122 1221 222) = det(2in)det(222-22127)'512) 이고 222. 1= 222- 221211' 212라고 하면

- 522. 15215

222:1 임이 알려져 있다.6) 이 사실을 이용하여 조건부분포의 확률밀도함수

## 61) 부분행렬로 분할된 행렬에 관한 이러한 사실은 부록 II에 증명되어 있다.

<!-- page 178 -->

pdfxx,=1,(22)(1)= pdfxpx,(21)52)/pdfx, (ar) 를 계산하여 (b)를 밝힐 수 있다. 또는 (b)와 82-12-52127(8,-M)x,=2~N(0,222-221271712) 가 동등한 것을 이용하여 다음과 같이 (b)를 밝힐 수도 있다.

## X1-M1

따라서 <정리 4.4.3>의 (a)로부터

## X.-M

## 2-M2-221211(X,-Mr)

그러므로 <정리 4.4.3>의 (b)로부터 X, -서과 X2-M2-221571(X, -M) 은 서로 독립이고

## 82-12-22151(8,-14)~N(0,522-521571512)

이다. 따라서 (b)의 조건부분포가 성립한다. 예 4.4.3 이변량 정규분포 N(41, 42:03,63,p)에서의 조건부분포 A2X,=E,~N(+po2(81-1)/01:02(1-p2)) 정리 4.4.5 이차형식의 분포

## (a) X~ N: (W, 2)이고 분산행렬 2가 정칙행렬이면

## (X-K)너'(X-K) ~ x2(K)

(6) 2~N(0,1)일 때, A2=4이면 2'4Z~x2(x)이고 자유도는 r= trace(A) 이다.62)

62) 일반적으로 2' Ac= 2'

## 1+A'

## • z이므로 이차형식 Z'AZ 에서 행렬 A는 언제나 대칭행

렬인 것으로 가정되어 있으며, (b)에서의 조건 A>=A는 Z'AZ~x'(x) 이기 위한 충분 든 대각원소의 합이다. 조건일 뿐만 아니라 필요조건인 것도 알려져 있다. 여기에서 trace(A)는 행렬 A의 모 184 4장 표본분포

<!-- page 179 -->

[증명] (a) 512512= 2인 대칭행렬 21/2의 역행렬을 5-12이라고 하면 2125(212)= 512515125112=1 이므로 <정리 4.4.3>의 (a)로부터

## 512(X-K) ~ Nx(0,I)

따라서 Z= (Z1,…Zx)'= 21/2(X-w)라고 하면 (x-K)51(X-K)=2'Z=23+·+2k, 2~N(0,1)(&= 1,:,k) 그러므로 카이제곱분포의 대의적 정의로부터

## (X-K)'너-(X-K)~x2(6)

(b) 행렬 A는 원소가 실수인 대칭행렬이므로 다음과 같이 대각화가 가능하다.63) ^1 0 .. 0 A= Pl 0 12 •. ( : . : P, P'P= PP'= 1

## 0 . A,

여기에서 11,••, 1,은 det(A- AI)= 0을 만족하는 1값들로서, 42= 4인 경우에는 1’= 1,이어야 하므로 1,는 0 또는 1임을 알 수 있다. 이들 중 7 개만 1이고 나머지는 0이라고 하면 시,=…•= 1,=1, A,+1=…= 1,=0 이라고 가정할 수 있다. 따라서 7x r인 단위행렬을 1, 이라고 하면 2:42=(P21160(P2) 그러므로 X= (X1,…,X,)'= PZ라고 하면 242=X 60×=X3+·+X3,X~N,(0,Pp)=N.O.1) . Z'AZ=X3+…+X3, X,~N(0,1)(i= 1, ,7) 그러므로 카이제곱분포의 대의적 정의로부터 Z'42~x2(7)

63) 원소가 실수인 대칭행렬의 대각화에 대한 정리는 부록 II에 주어져 있으며, det(A- AI) = 0 을

만족하는 A 값은 행렬 A의 고유값(터값, eigen value)이라고 한다.

<!-- page 180 -->

예 4.4.4 일원분류모형에서의 표본분포 <정리 4.2.72의 (a)에서는 일원분류모형에서 정규분포 N(o2/n.)를 따르고 서로 독립인 표본평균 X; (i= 1,…,k)에 관한 다음의 표본분포를 소개하고 있다. 2n(Xi-x-(-p)/02~x2(6-1) 이제 <정리 4.4.5>를 이용하여 이 결과를 밝히기 위하여 Y;=X;-X-(-w) (i= 1,,k), Y=(Yl,Y,), n=k-1 라고 하면,

## 로부터 Y,들의 평균, 분산, 공분산을 다음과 같이 구할 수 있다.

E(Y:)=0, Var(Y:)=(n:1-m1)o; Cov(YY;)=-n 1o2(ij=1,…k)(i= j) 따라서 Y=(Y:;,Y,)'~N,(0,2), 2=[D(7;1)-n2119102 D(p;1)= "??... :.. 1= (1,…,1)'

## 한편 부록 II의 특수한 형태의 행렬에 관한 연산64)으로부터

[D(n))-n1171=[1-nD-(n1)1111D-17;)) n 0 D(%;) = 0 72 ", 또한 <정리 4.4.5>의 (a)로부터 Y'5-ly~ x2(x)이므로

## Mn(X-계-(-F)3102~×2(6-1)

64) 벡터 0, 6에 대하여 1+6'a= 0이면

(1+a6)-1=I+cad', c= -1/(1+6:a) 186 4장 표본분포

<!-- page 181 -->

예 4.4.5 표본분산의 표본분포 정규분포 N(4,0)에서의 랜덤표본을 X1, X 2, ··, X,, 이라고 할 때, 표본평균 X 와 표본분산 S2=LS(X,-X):/(2-1)은 서로 독립이고 (n-1)s3/~ x2(n- 1)인 것을 <정리 4.2.2 로부터 이미 알고 있다. 이제 다변량 정규분포에 관한 정리들을 이용하여 이를 밝히는 방법을 알아보자. 이를 위하여 X = (X 1,••,X,,)'라 고 하면 X~N, (1, 021), 1= (1,,1) 2-n18. 17-1)5°-0.-78=x10-012)× 한편 1-n- 11'은 대칭행렬이고 1'(I-n-'11')= 0이므로 Cov(1X, (1-n 111')X)= 1'(021)(1-n- 1115) = 0 따라서 정리 4.4.3>의 (c)로부터 X=n-|1'X와 (I-n-'11')X은 서로 독립 이다. 그런데 (1-”-111')? =1-n 111' 이므로 X'(I-n1115)X=[(1-m 1115)X)[(1-n 111')X] 그러므로 X와 (n-1)S2=X'(I-7'11')X은 서로 독립이다. 또한 x'(1-n111)x/0=(x-ul)'(1-n 1115)(X-(1)/82 이고 (X-11)/0~ N,,(0,1), (1-n 111')2=1-21113 , trace(I-nl1lt)=n-1 이므로 <정리 4.4.5>의 (b)로부터 (n-1)s2/02=X'1-m-1115)X/02~ x2(n-1) 통계 조사에서 변수 사이의 함수관계를 파악하고자 하는 경우가 많이 있다. 이러한 함수관계 조사를 목적으로 가장 기본적으로 사용되는 모형이 다음의 선형회귀모형(#. 펩 미&펜, linear regression model)이다. 이는 설명변수(출산 해 , explanatory variable) 20: 21, , 2,와 오차항 e에 의해 반응변수(K M , response variable) Y가 정해진 다는 전제 하에 그 관계가 선형이라고 가정하고 반복 관측된 Y 값을 이용하여 선형관 계의 구체적 형태를 추측하고자 하는 것이다.

<!-- page 182 -->

선형회귀모형(정규 오차항을 갖는 경우): Y;=200+lib too+liphp te, (e~N(0,02), i=1,,m iid 이러한 선형회귀모형을 벡터와 행렬을 사용하여 나타내기 위하여 Xno Xnl Xnp 라고 하면 위의 모형을 다음과 같이 간략하게 나타낼 수 있다. Y=Ab-e (e~N, (0,0:T) 여기에서 설명변수의 행렬 X는 주어진 상수의 행렬로서 7X (p+ 1)의 계수(B) 1, rank)o)가 (p+ 1)인 것으로 가정하고, 선형관계의 구체적 형태를 나타내는 B=(Bo, 3,,…,B,)'를 회귀계수(DS% w, regression coefficient)라고 하며, 이의 추 측 값으로는 흔히 B =(XX) ITy 로 정의되는 표본회귀계수( 미금 (주 , sample regression coefficient)를 사용한다. 예 4.4.6 단순선형회귀모형에서 표본회귀계수 선형회귀모형에서 pp= 1이고 20= 1인 경우, 즉 Hi= Botlibite, (e;~N(0,02), i=l,….n 로 나타내어지는 모형을 단순(®※t, simple)선형회귀모형이라고 한다. 이 경우에는 X= 1ㅉ11 X'y= Zml (X(X) 1=

## 65) 행렬의 계수에 대한 정의와 설명은 부록 II에 주어져 있다.

188 4장 표본분포

<!-- page 183 -->

이므로 표본회귀계수 B= (Bo,5,)'는 다음과 같이 주어진다. 31= 66=7-215, 즉 5ot2:18,=8+(211-21)31 선형회귀모형에서 오차항의 분산 o'의 추측값으로는 흔히 Q=(y-XB)'(Y- XB)/(n-p-1) 로 정의되는 평균오차제곱합(주)#※ 제곱합, mean squared error sum of squares)을 사 용한다. 예 4.4.7 단순선형회귀모형에서 평균오차제곱합 <예 4.4.6~의 단순선형회귀모형에서 평균오차제곱합은 Q= 정리 4.4.6 선형회귀모형에서 표본분포에 관한 기본 정리 선형회귀모형 IY= Apte Ie~N,, (0,01) 에서 주어진 상수의 행렬 X는 nX(p+ 1) 행렬로서 계수가 (p+ 1)인 것으로 가정할 때 다음이 성립한다. (a) 3~ Np+1 (6,02(X'X) 1) (6) 표본회귀계수 3와 평균오차제곱합 2은 서로 독립이다. (c) (n-p-1)0:/02~ x2(n-p-1) [증명] (a) Y~ N(X3,021)이므로 <정리 4.4.3>의 (a)로부터 B=(htx)-xly~N((rx)-Xx3,02(Xx) X(38)-X))

## . B~N(3,02((XX) 1))

<!-- page 184 -->

(b) II= X(X'X)-'X'라고 하면 II는 대칭행렬로서 II2=X(XX) XXXX)M=I, IIX=M(XX)TX=A 인 것을 알 수 있다. 한편 Y-KB=Y-IIY = (1-I1)y . Cov((X'X)-LXy, (I-II)Y)=(X'X) 1X1(02)(1-m)'=0 따라서 <정리 4.4.3의 (C)로부터 B=(X'x)-'X'y와 y-xp= (1-17)Y 는 서로 독립이고, 이로부터 3와 2=(Y-x3)(Y-x3)/ (n-p-1)이 서 로 독립임을 알 수 있다. (c) (b)에서의 행렬 II에 대하여 (1-II): =I-Il, (1- II)X= 0 이므로 (Y-XB)'(Y-X3)=Y'I-I)'(I- II)y =(Y-Xg)'(I-II)(Y - Xg) : (n-p-1)812=(x-x3)(x-28)22=(x-x3)(1-m)(y-Xa)02 여기에서 (1-x9)/0~N,,(0,1), (I-I): = (1- II), trace(I- II)= n-p-1600 이므로 <정리 4.4.5>의 (b)로부터 (n-p-1)02/02=(Y-X3)(1-m)(Y-X3)/02~ x2(7-70-1) 예 4.4.8 단순선형회귀모형에서의 표본분포 <예 4.4.62, <예 4.4.7>과 <정리 4.4.6>으로부터 단순선형회귀모형에서는 B=B (0-2)022-208-8(80-87)8102-22(0-2) 이고 3과 22이 독립이다. 따라서 t 분포의 대의적 정의로부터

## 66) 행렬의 덧셈과 곱셈의 정의로부터 대각합에 대한 다음 성질이 성립하는 것은 명백하다.

trace (Inxn-X(XX)-K)=ntrace((XX)-'XX)=n-D-1 trace(A+B) =trace(A) ttrace(B), trace(AB) = trace(BA) 190 4장 표본분포

<!-- page 185 -->

## B,-31

(6-B,)/ v62/Six -~t(n-2) V 215kx V(n-2)(62/02)/(n-2) 이 경우에 평균오차제곱합은 다음의 공식을 이용하여 계산할 수 있다. 2-M(2,-7-8)(0:-21)2(m-2)={Srr-(Sar)/So/(7-2) 다변량 정규분포의 성질 : (2) AN(, 5)+ 6=N(AN+6,ASA) (3) N(4,22)0N6235)=N(+8229,+22)

## (4) X~N (W, 2)일 때,

AX IBX F Cov(AX,BX)= AIB'=0 (5) x ~N(m,(mum2) 221 2:221 5 (a) X,~N(W,Min) and (6) Xzx,=8,~N(+221271(81-1), 222-2215712212) (6) N(O,I) AN(O,1)~x'() A'=A, r=trace(A)

<!-- page 186 -->

대표적 표본분포 분포의 명칭과 기호 (representational definition) 대의적 정의 (distribution) 확률밀도함수 (pdt) 카이제곱분포 X~x?(7)=X~Gamma(x/2,2) x2(7) 1X= 71+•+%,, 2~N(0,1)(i=1,,7) (7= 1,2,…·) pdfx(z)=- t 분포 X~t(7) (r= 1,2,…·) t(r)

## VV,, Z~N(0,1), V~x2(7), Z, V는 서로 독립

pdfx(z)= 21/2)7m/12) 7 (1+23)+12 [((×+1)/2) X~F(i72)

## F 분포

BX= , Vi~X (7)(호=1,2), Vi, VV는 서로 독립

## F(71,72)

(7= 1,2,··)(i=1,2) pdfx(a) 7(p:/2)r(72/2) [((/+72)/2) 7/2 2"/2-1/ 1+" -(71tr2)/2 ¼=≥0) 베타분포 1~ Beta(a1, 02) Beta(a1,a2) Bx=2/(2,+2), 2,~Gamma(ans) (:=1,2)이고 서로 독립 (a1>0,02≥0) wes(a)= 7(a) (e) 29-(1-2)°-'han(a) [(a,taz) X=(Xr,xx)'~Dirichlet(a1),0kck+1) Xx 디리클레분포 X; ~Gamma(a;9)이고 서로 독립(i=1, ,k+1) Dirichlet(a1,ak+1) (a,>0, i=1,,k+1) C=T(a):Mak+) [(ast:tax+i) 192 4장 표본분포

<!-- page 187 -->

일원분류보형 다변량 정규분포 신뢰 십합 지환 계수 회귀계수 고유값 선형회귀모형 정칙행렬 정칙 다변량 정규분포 확률적뿐변환 중심극한정리 표본회귀계수 단순 설명변수 점근 대수의 법칙 표본적율 극한분포 표본분위수 점근분 포장안오주 난수 첨예도 균등난수 표본상관계수 분위수 가능도 추정법 추정 추정량 일치성 몬테칼로 적분 분산안정변환 가능도 할수 적률이용추정량 다중모수 지수족 점수합수 연습문제 가능도방정식 쿨백-라이블러 괴리도 순오목함수 공간 확률측도 정사영 조건부확률 리 최소제곱 추정법 표본공간 . 최소제곱 추정량 점근정규성 사전 확률 가산가법성 확률밀도함수 랜덤한 실험 확률변수 이산형 사후 독립 | 표할수 평규 기댓값! 연속형 표주편차 이상 확률분포 화률질량함수 표주화 4.11 균등분포 U(-ㅠ/2,/2)를 따르는 확률변수 X에 대하여 Y = tanX 의 확 률밀도함수를 구하여라.

## 4.2 확률변수 X 1, X의 결합확률밀도함수가

일 때 Y,=X1, Y2=X2-X,의 결합확률밀도함수를 구하고, Y, 과 Y2가 서로 독립인가를 판단하여라

## 4.3 확률변수 X 1, X 2의 결합확률밀도함수가

f(21,22)= 80182(0<8,CI2C1) 일때 Y,=X./X2, Y2=X2의 결합확률밀도함수를 구하고, Y1과 12가 서 로 독립인가를 판단하여라.

## 4.4 확률변수 X1, X 2: X3의 결합확률밀도함수가

일때 Y,=Xr, Y2=X2-XI, Yg=Xg-X,의 결합확률밀도함수를 구하고,

## YI, Y2, Y3가. 서로 독립인가를 판단하여라.

## 4.5 확률변수 X1, X 2, X3가 서로 독립이고 각각의 주변확률밀도함수가

1(2)=e 21(0,∞)(2) 일 때 다음에 답하여라. (a) Y,=X1, Y2=X,+X2, Y3=X1 +X2 +X3의 결합확률밀도함수를 구하 여라. (b) Y1; Y3의 결합확률밀도함수를 구하여라.

<!-- page 188 -->

## 4.6 확률변수 X 1, X2 의 결합확률밀도함수가

1.2(01:22)=2e812210cm1 KisCa) 이고, Y,=X,/X2, Y2 =X2라고 할 때 다음에 답하여라. (a) Y」의 확률밀도함수를 구하여라. (b) E(Y2lYr)와 Var(Y2lYi)을 구하여라.

## 4.7 확률변수 X1, X 2의 결합확률밀도함수가

일 때 Y= X,+X2의 확률밀도함수를 구하여라. 4.8 확률변수 X의 확률밀도함수가 다음과 같은 경우에 Y = X 2의 확률밀도함수 를 구하여라. (a) 1(z)= 한-2,2)(2) (B) 1(C)= ¼1-13)(C)

## 4.9 확률번수 X 1, X2의 결합확률밀도함수가

f(21;a2) = 일 때 다음에 답하여라. (a) 극좌표 형식인 X,=Rcose, X2=Rsine,R≥0,0≤0< 2T로 정의

## 되는 R, 의 결합확률밀도함수를 구하여라

(6) Y,= VX:+X3, Y2=

## X1

Vx?+X3

## 1일 때 Y1, Y 2의 결합확률밀도함수를

구하여라. 4.10 발생률이 1인 포아송과정 {N, :t≥ 0}에서 7번째 현상이 발생할 때까지 의 시간을 W,=minft:N, 2 7j(r= 1,2,) 이라고 할 때 다음에 답하여라. 194 4장 표본분포

<!-- page 189 -->

(a) (Yi, Y 2;, Yx)' =(W:/Wk+1:(W2-W)/Wk+1,,(Wk-Wx-1)/Wk+1) 의 결합확률밀도 함수를 구하여라. (b) (X,Y)'=(W2/Ws: WA/Ws)의 결합확률밀도함수를 구하여라.

## 4.11 확률변수 X가 F(r1:r2) 분포를 따를 때

Y= (71/r2)X 1+(71/r2)X 는 Beta(ri/2, 72/2) 분포를 따르는 것을 밝혀라.

## 4.12 확률변수 X 1, X2 , X, 이 서로 독립이고 동일한 주변확률밀도함수

f(z)= 32210,1)(2) 를 따를 때 다음에 답하여라. (a) Y=, min X; 의 누적분포함수를 구하고, 그 도함수로서 확률밀도함수 1≤isn 를 구하여라. (b) Y=, max X; 의 누적분포함수를 구하고, 그 도함수로서 확률밀도함수 를 구하여라.

## 4.13 확률밀도함수

J(a) = 2x1(0.1)(z) 를 따르는 세 확률변수에 기초한 순서통계량을 X(1) < X(2) <X(3)이라고 할 때 다음에 답하여라. (a) Y,=X(1)/X(2), Y2=X(2)/X (3), Y3 = X(3)가 서로 독립임을 밝혀라.

## (6) 조건부기댓값 E(X(2) X (3))을 구하여라.

4.14 V(1) < U(2) <…< U(m)이 균등분포 U(0,1)로부터의 랜덤표본 U1, U2,

## ••, U,, 에 기초한 순서통계량일 때 다음에 답하여라.

(a) 11=U(1)/V(2)::,1m-1= U(n-1)/V(n)의 결합확률밀도함수를 구하여라, (b) Y,(1≤ 7≤n-1)의 주변확률밀도함수를 구하여라.

<!-- page 190 -->

4.15 U(l) < U(2) <…< U(n)이 균등분포 U(0,1)로부터의 랜덤표본 V1, U2, •·, Un에 기초한 순서통계량일 때 임을 설명하고, 이를 이용하여 다음 등식이 성립함을 밝혀라. 4.16 U(1) <U(2) <…< U(n)(n≥2)이 균등분포 U(0,1) 로부터의 랜덤표본 U1, V2, , Un에 기초한 순서통계량일 때, Y=U(n) - U(1)의 확률밀도함 수를 구하여라. 4.17 X(1) <X(2) <…< X(n) (p≥ 2) 이 지수분포 Exp(1)로부터의 랜덤표본 X 1, , Xm에 기초한 순서통계량일 때, Y=X(n)- X(1)의 확률밀도함수를 구하여라.

## 4.18 균등분포 U(0, 1)를 따르는 확률변수 U에 대하여

X= 8(-10g(1-U)'0, a>0,320 라고 할 때 다음에 답하여라. (a) X의 확률밀도함수가 다음과 같이 주어지는 것을 밝혀라. 1(z)= 0020-lexp(-2°/39)(0+o) (2) 이 분포를 와이불(Weibull)분포라고 하며 기호로는 X~ Weibull(a,B)로 나 타낸다. (b) X의 확률밀도함수와 누적분포함수를 각각 f(2), F(2) 라고 할 때 1-F(2) e 0201, 020 f(z) 임을 밝혀라. 확률변수 X가 수명을 나타낼 때 이러한 함수는 수명이 2 인 순간에서의 사망률(mortality rate)을 나타내는 함수로서 흔히 위험률(*, hazard rate) 함수라고 불리운다. 196 4장 표본분포

<!-- page 191 -->

## 4.19_ 균등분포 U (0,1)을 따르는 확률변수 U에 대하여

## 라고 할 때 X가 로지스틱분포 L(0,1)을 따르는 것을 밝혀라.

## 4.20 균등분포 U(0,1)을 따르는 확률변수 U에 대하여

X = tan((U-1/2))

## 라고 할 때 X가 코쉬분포 C(0,1)을 따르는 것을 밝혀라.

4.21 V(1) < U(2) <…<V(m)이 균등분포 U(0,1)로부터의 랜덤표본 U1, U2,

## •··, U,,에 기초한 순서통계량일 때 다음을 밝혀라.

(a) (Uc)1srsne(1-Uc-r+l)soca (-logU(r))1sr≤n=(-10g(1-U(n-r+1)1≤r5n (C) U(n+ 1) = 1이라고 할 때 (-logU(r)/U(r+l)])isrsn=(Zn-rtl)sysn, 2,~Exp(1) (d) U(n+1) = 1이라고 할 때 (U(r)/U(x+1)「~U(0,1), r= 1,,2

## 4.22 함수

ss3)=2807(+8)(1+28280-76+8-211

## 가 확률밀도함수임을 밝히고, 이 함수가 확률변수 X, Y의 결합확률밀도함수

## 일 때 X, Y의 주변분포가 각각 N(0,1)임을 밝혀라. 이로부터 주변분포가

일차원의 정규분포이면서도 결합분포는 이변량 정규분포가 아닐 수 있음을 알 수 있다.

## 4.23 확률변수 X 1, X2 X3가 서로 독립이고 각각이 N(0,1)을 따를 때, 다음과

## 같이 이들을 구면좌표로 나타내는 R, O1, 02의 결합확률밀도함수를 구하여라.

Al=Rcoseisine2: A2=RSIneisin02, A3= Rcos62

## ,. 0502X7

<!-- page 192 -->

4.24 X= (X1,X2,X3)'~ N(W,2)이고 A와 I가 아래와 같을 때 다음에 답하여라. ㅻ= 너=! 1-1 (a) Y=(X, -X2+X3, 2X, +X2-X3)'의 분포를 구하여라. (b) Xg= 23이 주어진 조건에서, (X1, X2)'의 조건부분포를 구하여라. 4.25 <예 4.4.6>과 <예 4.4.7>에서의 단순선형회귀모형에서 다음이 성립하는 것 을 밝혀라. Bo+Bi21-(30+8,21) (21- 21)2 ~t(n-2) 4.26 (X1,Y,)', , (X,, Yn)'(n> 2)이 이변량 정규분포 (p0102 03 에서의 랜덤표본이고, 7이 표본상관계수 즉 이라고 하자. 또한, Z;=(X:-11)/01 W.={(Y:-M2)/02-p(X;-m)/0/V1-p2(i=1,…,n) 이라고 할 때, 다음에 답하여라. (a) SizplVI-p'+ Sim V1-p2 VSuaSww-Sim 임을 밝혀라. 여기에서 Sa= 52,-5),Srw=M(WW), 5= 5:0,-5)(W.8) 198 4장 표본분포

<!-- page 193 -->

(6) T=((21-2)/VSzz, , (2,-2)/ VSca)라고 할 때, 다음을 밝혀라. (Sww-stm/Szz=W'(I-1(11)-11'-T(TT)-1T'}W (c) (Z1, ,Zn)'과 (Wr, ., Wn)'이 서로 독립임을 밝히고, 이를 이용하여 다음을 밝혀라. (a) Sww-S:/ Szz x2(n-2)이고, (Z1,…,Zn)'과는 독립이다. (i:) Saw/WSiz~N(0,1) 이고 (Z1, ,Zn)'과는 독립이다. (ii:)Sww-Stw/Suz, Saw/wSiz, Scz는 서로 독립이다. (d) 다음이 성립함을 밝혀라. -= dyViplV1-84U v1-p v2 V, ~ x2(7-1), V2~ x2(n-2), U ~ N(0,1) 이고 Vi,V2,U는 서로 독립

<!-- page 194 -->

bability density function) 연속형(표 continuous type) 이상(꽃: improper) 확률분포(주5fi probability distribution) 지표함수(3704 ment) 확률변수(B문제청 random variable) 이산형(발 discrete type) 확률질량함수(Ht 2P ex 8y probability mass fuction) 확률밀도함수(16 function) 평균(주) mean) 기댓값(1A값 expected value) 표준편차(39 standard deviation) 표준화(1%41t. standardized) 누적분포함수 주소 9y probability generating function) 적률생성함수(181 5). 9y moment generating function) 적률(1 moment) 누율생성하 제 cumulative distribution function) 표준지수분포(부)977 standard exponential distribution) 급수(류 9분 power series) 확률생 KBs cumulant generating function) 누율(#후 cumulant) 이변량(bivariate) 확률벡터 (random vector) 반복적분(iterated integra" ioint) 주변(Bi margina) 공분산(#5w covariance) 상관계수(#EBE CS 9 correlation coefficient) 결합적률(슴#푸 joint mor 조건부(1%44B conditional) 조건부평균(conditional mean) 조건부기댓값(conditional expected value) 조건부분산 석률생성함수(joint moment generating function) 결합누울생성함수(joint cumulant generating function) 합누율 jaint r ector) 전치(transpase) 평균벡터(mean vector) 분산공분산행렬(variance covariance matrix) 정부호 al variance) 회귀함수(미#aph regression function) 평균제곱예측오차(mean squared prediction error) 행벡F tive definite) 기울기벡터(gradient vector) 헤시안행렬(Hessian matrix) 모집단(뜻해 popul 1단분포(B%BAt population distribution) 비복원추출(sampling without replace BIt# population proportion) 초기하분포(재원(tF hypergeome =랜덤추출(T*+랜덤Itt simple random sampling) 랜덤표본(random sampl ution) 복원추출(1TTtt sampling with replacement) 이항분 T binomial distribution) 대의적 정의(fEE11 교통 repr nal definition 다항분포(3141 multinomlal ar 포(wft t geometric distribution) ) 다항계수(309 w multinomial coefficie ion) 음이항전개식(negative =(-WA T negative binomia expansion) 포아송(Poiss : 과정(Poisson process) currence rate) 정상성 ty) 독립증분성 (indepe 회귀성(rareness) 지수분 'ement) 비례성(propo ential distribution) 감마분 표본분포의 근사 e parameter) 척도모수(FRA 명 a distribution) 형상모수(HEANA imeter) 표준정규분포(## TERAt s ormal distribution) 분위수(upper quanti 비율(# Hw sample proportion) 표본평균(MA 4H) 간(타수m parameter space) 통계량(Wit m sta tatistics) 표본중앙값(1KF5값 sample medi an) 표본분포(주))16 ean) 표본분산(#zAw sample variance) 순서통계량(NET:ACBt) r) 이중지수(double exponential) 코쉬(Cauchy) 균등분포(1955 th uniform distribuu distribution) 위치모수(호법 다용) ocation parameter) 척도모수(RIg scale 브포(chisquared distribution) 신뢰수준(183 confidence level) 신뢰구간(1Sil confidence =1Af triangular distribution) 야코비안(Jacobian) 자유도(BtlE degrees of freedon.

## 분류모형(ㅡT유#*포

probability integral transformation) 다변량 정규분포(3 FERA17 multivariate no. one way classification model) 신뢰집합(1룸. confidence set) 치환(71월 per) on) 정칙행렬(nons ingular matrix) 정칙 다변량 정규분포(1E 3로 INAm nonsingular multivariate normal disti. 집값 characteristic value) 선형회귀모형(19미% linear regression model) 설명변수(explanatory variable) 반응변수. 급합(주식#※제곱합 mean squared error sum of squares) 중심극한정리(PPL)3또 central limit theorem) 극한분포(AR9)76 limitra able) 계수(11% rank) 회귀계수(1일(%% regression coefficient) 표본회귀계수(sample regression coefficient) 단순 Wt simple) 연 on) 점근분포(WiviANth asymptotic distribution) 대수의 법칙(*※의 ※R law of large numbers) 표본적률(sample moment) 분위수(A) 11 93) n coefficient) 분산안정변환(AW57%) variance syabilizing transformation) 난수(8lg random number) 균등난수(1)4 8l.gt uniform randon 표본분위수(백 5(1 w sample quantile) 슬럿츠키(Slutsky) 근(Wit asymptotic) 첨예도(ak kurtosis) 표본상관계수 (1 7A) 0w a sample 몬테칼로적분(Monte Carlo integration) 적률이용추정량(표지112m method of moments estimator(MME)) 추정(HT estimation) 추정량(Ht. tor) 일치성(-t consistency) 가능도 함수(미 NE 9) ) 가능도방정식(미#% 7#it ikekihood equation) 순오목함수(strictly concave function) 경계(16 boundary) 다중모수 지수족 (3) B 9) 1품): multil wit likelihood function) 우도(X) 최대가능도 추정법(XE Ht: maximum likelihood e 3pe information number) 최소제곱 추정법(least squares estimation) 최소제곱 추정량(least squares estimator) exponential family of pdf's) 쿨백-라이블러 괴리도(Kullback-Leibler divergence) 근정규성(Mii iERtt asymptotic normality) 점수함수(score functic ndicular projection 공리(AT axiom) 표본공간(배호m sample space) 확률(mm probability) 가산가법성(countable additivity) 확률측도(1838k probe 열벡터 공간(column space) 정사영(IE) ure) 조건부확률 실험(random experiment) 확률변수(178 random variable) 이산형(월 discrete type) 확률질량함수(#부별로: probability mass fuction) 률밀도: (13116 conditional probability) 사전(Tml prior) 사후($t posterior) 독립(3t mutually independent) 종속(NEt mutually depende unction) 평균(4k mean) 기댓값(19 TE Bws probability density function) 연속형(i토 continuous type) i값 expected value) 표준편차(148초 standard deviation) 표준화(33ft standardized) 누적분포함수(FA) 1T E E 이상(물: Improper) 확률분포(mpA th probability distribution) 지표함수(1660 19 stribution function) 표준지수분포(#부):Ath standard exponential distribution) 멱급수(₩ww power series) 확률생성함수(8주소:w probability g nction) 적률생성함수(MPLitt moment generating t) 이변량(bivariate) 확률벡터(random vector) 반복적분(iterated integral) 결합(금 joint) 주변(Emarginal) 공분산(A컵 covariance) 상관계수(*E ANG% function) 적률(8) # moment) 누울생성함수(#부소&: cumulant generating function) 누율 (복 on coefficient) 결합적률(#슴 율(joint cumulant) 조건부(19f7 # conditional) 조건부평균(conditional mean) 조건부기댓값(conditional expected value) 조건부분산(conditional variand joint moment) 결합적률생성함수(joint moment generating function) 결합누율생성함수(joint cumulant generating ur ESpats regression function) 평균제곱예측오차(mean squared prediction error) 행벡터(column vector) 전치(transpose) 평균벡터(mean vector) 분산: variance covariance matrix) 정부호(nonnegative definite) 기울기벡터(gradient vector) 헤시안행렬(Hessian matrix) 모집단(SE population) 모집단 비율(Bltf population proportion) 초기하분포(NA fi hypergeometric distribution) 복원추출(19Tlts sampling with replacement) 이항분포 ht population distribution) 비복원추출(sampling without replacement) 단순랜덤추출(1※랜덤htt simple random sampling) 랜덤표본(random nomial distribution) 대의적 정의(1119 Fi representational definition 다항분포(318Af multinomial distribution) 다항계수(초트% multinor ient) 기하분포(*m) 1 geometric distribution) 음이항분포(F9) (Poisson) 포아송 과정(Poisson process) 발생률(occurrence rate) 정상성(stationarity) 독립증분성(independent increment) 비례성 (proportion, iasih negative binomial distribution) 음이항전개식(negative binomial expan 정규분포(144 E88.77 standard normal distribution) 분위수(upper quantile) 모수공간(&형포 parameter space) 통계량(8금 statistil reness) 지수분포(exponential distribution) 감마분포(gamma distribution) 형상모수(3 3HKg shape parameter) 척도모수(RE 6)% scale pal Aly sample proportion) 표본평균(#1419 sample mean) 표본분산 (추취 #*☆보값 sample medi an) 표본분포(wxhin sampling distribution) 위치모수(118g location parameter) 척도모수(FE 13북- sample variance) 순서통계량 (MITM im order statistir cobian) 자유도(Btls degrees of freedom) 카이제곱분포(chi-squared distribution) 신뢰수준(1등가* confidence level) 신뢰:7 er) 이중지수(double exponential) 코쉬(Cauchy) 균등분포 서쪽AT uniform distribution) 삼각분포(=RAth triangular distributic on) 확률적분변환 (1 1) 5 15 confidence interval) 일원분류모형 probability integral transformation) 다변량 정규분포(3e FRAm multivariate norr Il one way classification model) 신뢰집합(1룸월부 confidence set) 치환 (또 (EA값 characteristic value) 선형회귀모형(※미호 linear regression model) 설명변수(explanatory variable n) 정칙행렬(nons ingular matrix) 정칙 다변량 정규분포(1] 38e IERit nonsingular multivarlate normal distrit 순(8w simple) 평균오차제곱합(주)※※제곱합 mean squared error sum of squares) 중심극한정리(#LE) ionse variable) 계수(ht: rank) 회귀계수(미율(%) regression coefficient) 표본회귀계수(sample regression cr 칙(☆봉의 # law of large numbers) 표본적률(sample moment) 분위수(A(1 quantile) 표본분으 ral limit theorem) 극한분포(R976 limiting distribution) 점근분포(hfliAth asymptotic distributior 1t sample quantile) 슬럿츠키(Slutsky) 점근(Wit asymptotic) 첨예도 (499.5 kurtosis) 표본상 n+) 부사아저벼화 수법 ce syp
